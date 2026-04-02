import json
import os
import psycopg2
import requests
import sys
import time

from pathlib import Path

from .inserts import (insert_citation, insert_source, insert_works_author,
                      inserted_doi_data)
from .local_settings import config
from .utils import convert_unicodes


API_URL = "https://api.eventdata.crossref.org/v1/events"


def get_works_data(works_doi):
    cache_file = os.path.join(config['temporary-directory-path'], "cache",
                              works_doi.replace("/", "@@") + ".crossref.json")
    if not os.path.exists(cache_file):
        try:
            response = requests.get(
                    f"https://api.crossref.org/works/{works_doi}")
            with open(cache_file, "w") as f:
                f.write(response.text)

        except Exception:
            Path(cache_file).unlink(missing_ok=True)
            return None

    try:
        j = json.load(cache_file)
        return j
    except Exception:
        return None


def insert_authors(works_data, **kwargs):
    pid = {'id': works_data['message']['DOI'], 'type': "DOI"}
    sequence = 0
    for m_author in works_data['message']['author']:
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

            insert_works_author(pid, author, sequence, "CrossRef", **kwargs)
            sequence += 1


def find_citations(**kwargs):
    try:
        db = config['citation-database']
        conn = psycopg2.connect(user=db['user'], password=db['password'],
                                host=db['host'], dbname=db['dbname'])
    except Exception as err:
        kwargs['output'].write(
                f"***DATABASE ERROR from crossref.find_citations(): '{err}'\n")
        sys.exit(1)

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
                works_doi = event['subj_id'].replace("\\/", "/")
                works_doi = works_doi.split("doi.org/")[-1]
                success, new_entry = insert_citation(
                        doi, works_doi, "CrossRef", **kwargs,
                        conn=conn)
                if not success:
                    continue

                insert_source(works_doi, doi, "CrossRef", **kwargs,
                              conn=conn)
                if not inserted_doi_data(doi, publisher, asset_type, **kwargs):
                    continue

                if kwargs['no-works'] or not new_entry:
                    continue

                works_data = get_works_data(works_doi)
                if works_data is None:
                    kwargs['output'].write(
                            "***Unable to get CrossRef data for works DOI "
                            f"'{works_doi}'\n")
                    continue

                # add author data for the citing work
                insert_authors(works_data, output=kwargs['output'])

            next_cursor = j['message']['next-cursor']

    if 'conn' in locals():
        conn.close()
