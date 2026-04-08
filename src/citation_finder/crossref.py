import json
import os
import requests
import time

from pathlib import Path

from .inserts import (insert_citation,
                      insert_book_chapter_work_data,
                      insert_general_work_data,
                      insert_journal_work_data,
                      insert_proceedings_work_data,
                      insert_source,
                      insert_work_author,
                      inserted_doi_data)
from .local_settings import config
from .utils import (convert_unicodes,
                    db_connect,
                    regenerate_dataset_descriptions,
                    repair_string,
                    reset_new_flag)


API_URL = "https://api.eventdata.crossref.org/v1/events"


def get_work_data(work_doi):
    cache_file = os.path.join(config['temporary-directory-path'],
                              "citation_cache",
                              work_doi.replace("/", "@@") + ".crossref.json")
    if not os.path.exists(cache_file):
        try:
            response = requests.get(
                    f"https://api.crossref.org/works/{work_doi}")
            with open(cache_file, "w") as f:
                f.write(response.text)

        except Exception:
            Path(cache_file).unlink(missing_ok=True)
            return None

    try:
        with open(cache_file, "r") as f:
            j = json.load(f)

        return j
    except Exception:
        return None


def insert_authors(work_data, **kwargs):
    pid = {'id': work_data['message']['DOI'], 'type': "DOI"}
    sequence = 0
    for m_author in work_data['message']['author']:
        family = convert_unicodes(m_author['family'])
        given = convert_unicodes(m_author['given']).replace(".-", ". -")
        if len(given) > 0:
            author = {'family': family}
            parts = given.split()
            author['given'] = parts[0].replace("\\", "\\\\")
            author['middle'] = (
                    " ".join([e.replace("\\", "\\\\") for e in parts[1:]]))
            if 'ORCID' in m_author:
                author['orcid_id'] = m_author['ORCID']
                if author['orcid_id'].find("http") == 0:
                    idx = author['orcid_id'].rfind("/") + 1
                    if idx > 0:
                        author['orcid_id'] = author['orcid_id'][idx:]

            insert_work_author(pid, author, sequence, "CrossRef", **kwargs)
            sequence += 1


def insert_publication_data(work_data, **kwargs):
    typ = work_data['message']['type']
    if typ == "book-chapter":
        if 'ISBN' not in work_data['message']:
            kwargs['output'].write(
                    "Error obtaining CrossRef ISBN for book chapter (DOI: "
                    f"{work_data['message']['DOI']}\n")
            return

        insert_book_chapter_work_data(work_data['message']['DOI'],
                                      work_data['message']['ISBN'],
                                      work_data['message']['page'], *kwargs)
        return "C"
    elif typ == "journal-article":
        if ('container-title' not in work_data['message'] or
                len(work_data['message']['container-title']) == 0):
            pubname = work_data['message']['short-container-title'][0]
        else:
            pubname = work_data['message']['container-title'][0]

        pubname = pubname.replace("\\", "\\\\")
        volume = work_data['message']['volume']
        if 'issue' in work_data['message']:
            volume += f"({work_data['message']['issue']})"

        insert_journal_work_data(work_data['message']['DOI'], pubname,
                                 volume, work_data['message']['page'],
                                 **kwargs)
        return "J"
    elif (typ == "proceedings-article" or
            (typ == "posted_content" and 'subtype' in work_data['message'] and
             work_data['message']['subtype'] == "preprint")):
        if ('container-title' not in work_data['message'] or
                len(work_data['message']['container-title']) == 0):
            pubname = work_data['message']['short-container-title'][0]
        else:
            pubname = work_data['message']['container-title'][0]

        pubname = pubname.replace("\\", "\\\\")
        pages = (work_data['message']['page'] if 'page' in
                 work_data['message'] else "")
        insert_proceedings_work_data(work_data['message']['DOI'], pubname, "",
                                     pages, **kwargs)
        return "P"

    kwargs['output'].write(
            f"**UNKNOWN CrossRef TYPE: {typ} for work DOI: "
            f"{work_data['message']['DOI']}'\n")
    return None


def find_citations(**kwargs):
    kwargs['conn'], err = db_connect()
    if kwargs['conn'] is None:
        err = f"***DATABASE ERROR from crossref.find_citations(): '{err}'"
        raise RuntimeError(err)

    params = {'source': "crossref", 'obj-id': "", 'cursor': ""}
    for doi, publisher, asset_type in kwargs['doi_list']:
        kwargs['output'].write(
                f"    querying DOI '{doi} | {publisher} | {asset_type}' ...\n")
        next_cursor = "__first__"
        while next_cursor is not None:
            filename = (doi.replace("/", "@@") + ".crossref." + next_cursor +
                        ".json")
            filename = os.path.join(config['temporary-directory-path'],
                                    filename)
            if os.path.exists(filename):
                with open(filename, "r") as f:
                    j = json.load(f)

            else:
                num_tries = 0
                while num_tries < 3:
                    time.sleep(num_tries * 5)
                    try:
                        params['obj-id'] = doi
                        if next_cursor != "__first__":
                            params['cursor'] = next_cursor

                        response = requests.get(API_URL, params=params)
                        j = json.loads(response.text)
                        with open(filename, "w") as f:
                            f.write(response.text)

                        break
                    except Exception:
                        Path(filename).unlink(missing_ok=True)

                    num_tries += 1

                if num_tries == 3:
                    kwargs['output'].write(
                            f"Error reading CrossRef JSON for DOI '{doi}' "
                            "after three attempts")
                    next_cursor = None
                    continue

            if j['status'] != "ok":
                Path(filename).unlink(missing_ok=True)
                kwargs['output'].write(
                        f"Server failure for DOI '{doi}': '{j['message']}")
                next_cursor = None
                continue

            kwargs['output'].write(
                    f"      {len(j['message']['events'])} citations "
                    "found ...\n")
            for event in j['message']['events']:
                work_doi = event['subj_id'].replace("\\/", "/")
                work_doi = work_doi.split("doi.org/")[-1]
                success, new_entry = insert_citation(
                        doi, work_doi, "CrossRef", **kwargs)
                if not success:
                    continue

                insert_source(work_doi, doi, "CrossRef", **kwargs)
                if not inserted_doi_data(doi, publisher, asset_type, **kwargs):
                    continue

                if kwargs['no_works'] or not new_entry:
                    continue

                work_data = get_work_data(work_doi)
                if work_data is None:
                    kwargs['output'].write(
                            "***Unable to get CrossRef data for works DOI "
                            f"'{work_doi}'\n")
                    continue

                # add author data for the citing work
                insert_authors(work_data, **kwargs)
                # add type-specific data for the work
                pubtype = insert_publication_data(work_data, **kwargs)
                if pubtype is None:
                    continue

                # add general data about the work
                message = work_data['message']
                pubdate = {}
                if ('published' in message and 'date-parts' in
                        message['published'] and
                        len(message['published']['date-parts'][0]) >= 2):
                    dp = message['published']['date-parts'][0]
                    pubdate.update({'year': dp[0], 'month': dp[1]})

                if (len(pubdate) == 0 and 'published-print' in
                        message and 'date-parts' in
                        message['published-print'] and
                        len(message['published-print']['date-parts'][0]) >= 2):
                    dp = message['published-print']['date-parts'][0]
                    pubdate.update({'year': dp[0], 'month': dp[1]})

                if (len(pubdate) == 0 and 'published-online' in
                        message and 'date-parts' in
                        message['published-online'] and
                        len(message['published-online']['date-parts'][0])
                        >= 2):
                    dp = message['published-online']['date-parts'][0]
                    pubdate.update({'year': dp[0], 'month': dp[1]})

                if len(pubdate) > 0:
                    title = convert_unicodes(
                            repair_string(message['title'][0]))
                    insert_general_work_data(
                            work_doi, title, pubdate, pubtype,
                            message['publisher'], **kwargs)
                else:
                    kwargs['output'].write(
                            "***NO OR BAD PUBLISHER DATE for work DOI "
                            f"{work_doi} citing {doi}\n")

            next_cursor = j['message']['next-cursor']

    if kwargs['doi_group'] == "rda":
        regenerate_dataset_descriptions(service="CrossRef", **kwargs)

    reset_new_flag(**kwargs)
    kwargs['conn'].close()
