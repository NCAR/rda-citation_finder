import json
import os
import requests
import time

from .crossref import get_work_data as get_crossref_work_data
from .crossref import get_publication_date as get_crossref_publication_date
from .crossref import insert_authors as insert_crossref_authors
from .crossref import (
        insert_publication_data as insert_crossref_publication_data)
from .inserts import (insert_citation, insert_general_work_data,
                      insert_journal_work_data, insert_source,
                      insert_work_author, inserted_doi_data)
from .local_settings import config
from .utils import convert_unicodes, db_connect, repair_string, verified_DOI


API_URL = "https://wos-api.clarivate.com/api/wos"


def process_work(work_doi, work, **kwargs):
    work_data = get_crossref_work_data(work_doi)
    if work_data is not None:
        # add author data for the citing work
        insert_crossref_authors(work_data, **kwargs)
        # add type-specific data for the work
        pubtype = insert_crossref_publication_data(work_data, **kwargs)
        if pubtype is not None:
            # add general data about the work
            message = work_data['message']
            pubdate = get_crossref_publication_date(message, **kwargs)
            if len(pubdate) > 0:
                title = convert_unicodes(repair_string(message['title'][0]))
                insert_general_work_data(
                        work_doi, title, pubdate, pubtype,
                        message['publisher'], **kwargs)
                if pubdate['month'] == 0:
                    kwargs['output'].write(
                            "        Warning: missing publication month for "
                            f"work DOI {work_doi} citing {kwargs['doi']}\n")

                kwargs['output'].write(f"+++NEW CITATION: '{work_doi}'\n")
                kwargs['conn'].commit()
                return

    if 'pubdate' in locals():
        # didn't insert work data because of zero-length pubdate, so get from
        #  WoS record
        title = convert_unicodes(repair_string(message['title'][0]))
        insert_general_work_data(
                work_doi, title,
                {'year': work['static_data']['summary']['pub_info']['pubyear'],
                 'month': 0},
                pubtype, message['publisher'], **kwargs)
        kwargs['output'].write(
                "        Warning: missing publication month for work DOI "
                f"{work_doi} citing {kwargs['doi']}\n")
        kwargs['output'].write(f"+++NEW CITATION: '{work_doi}'\n")
        kwargs['conn'].commit()
        return

    if 'pubtype' in locals():
        kwargs['output'].write(
                "        ***No CrossRef publication type - WoS publication "
                "type: "
                f"{work['static_data']['summary']['pub_info']['pubtype']}\n")
        return

    # no work data available at all from CrossRef, so use what is in the WoS
    #  short record
    if work['static_data']['summary']['pub_info']['pubtype'] == "Journal":
        try:
            for name in work['static_data']['summary']['names']['name']:
                names = name['display_name'].split(",")
                author = {'family': names[0]}
                names = names[1].split()
                author['given'] = names[0].strip()
                if len(names) > 1:
                    author['middle'] = " ".join([e.strip() for e in names[1:]])

                insert_work_author(work_doi, author, name['seq_no']-1,
                                   **kwargs)

        except Exception as err:
            kwargs['output'].write(
                    f"***Error adding authors for WOS work {work['UID']}: "
                    f"'{err}'\n")
            return

        summary = work_data['static_data']['summary']
        titles = summary['pub_info']['titles']
        for title in titles:
            if title['type'] == "source":
                pubname = title['content']
            elif title['type'] == "item":
                work_title = title['content']

        insert_journal_work_data(work_doi, pubname, summary['pub_info']['vol'],
                                 "", **kwargs)
        insert_general_work_data(
                work_doi, work_title,
                {'year': summary['pub_info']['pubyear'], 'month': 0},
                "J", "", **kwargs)
        kwargs['output'].write(
                "        Warning: missing publication month and publisher "
                f"for work DOI {work_doi} citing {kwargs['doi']}\n")
        kwargs['output'].write(f"+++NEW CITATION: '{work_doi}'\n")
        kwargs['conn'].commit()
        return

    kwargs['output'].write(
            "        ***No CrossRef publication type and unknown WoS "
            "publication type: "
            f"{work['static_data']['summary']['pub_info']['pubtype']}\n")


def find_citations(**kwargs):
    kwargs['conn'], err = db_connect()
    if kwargs['conn'] is None:
        err = f"***DATABASE ERROR from wos.find_citations(): '{err}'"
        raise RuntimeError(err)

    headers = {'X-ApiKey': config['services']['wos']['api-key']}
    wos_id_params = {'databaseId': "DCI", 'count': 1, 'firstRecord': 1,
                     'viewField': "none", 'optionView': "SR"}
    for doi, publisher, asset_type in kwargs['doi_list']:
        kwargs['output'].write(
                f"    querying DOI '{doi} | {publisher} | {asset_type}' ...\n")
        # get the WoS ID for the DOI
        wos_id_params['usrQuery'] = f"DO={doi}"
        response = requests.get(API_URL, headers=headers, params=wos_id_params)
        try:
            j = json.loads(response.text)
        except Exception:
            kwargs['output'].write(
                    f"WoS response for DOI '{doi}' ID is not JSON\n")
            continue

        if (response.status_code == 429 and 'code' in j and j['code'] ==
                "Throttle Error"):
            kwargs['output'].write(
                    "    ***ABORTING due to throttle error "
                    f"'{response.text}'\n")
            break

        try:
            response.raise_for_status()
        except Exception as err:
            kwargs['output'].write("HTTP error {} for DOI '{}': '{}'\n".format(
                    response.status_code, doi, err))
            continue

        try:
            wos_id = j['Data']['Records']['records']['REC'][0]['UID']
        except Exception:
            kwargs['output'].write("      No WoS ID found")
            continue

        if len(wos_id) == 0:
            kwargs['output'].write("      Empty WoS ID found")
            continue

        kwargs['output'].write(f"      WoS ID: '{wos_id}'\n")
        # get the WoS IDs for the "works" that have cited this DOI
        works_id_params = {'databaseId': "WOS", 'uniqueId': wos_id,
                           'count': 100, 'firstRecord': 1, 'viewField': "",
                           'optionView': "SR"}
        num_records = 2
        while works_id_params['firstRecord'] < num_records:
            time.sleep(0.6)
            response = requests.get(os.path.join(API_URL, "citing"),
                                    headers=headers,
                                    params=works_id_params)
            try:
                j = json.loads(response.text)
            except Exception:
                kwargs['output'].write(
                        "WoS response for citing works for DOI/WoS_ID "
                        f"'{doi}/{wos_id}' is not JSON\n")
                works_id_params['firstRecord'] = num_records
                continue

            for work in j['Data']['Records']['records']['REC']:
                work_doi = None
                try:
                    for identifier in (work['dynamic_data']['cluster_related']
                                       ['identifiers']['identifier']):
                        if identifier['type'] == "doi":
                            work_doi = identifier['value']

                except Exception:
                    pass

                if work_doi is None:
                    kwargs['output'].write(
                            "***Unable to get DOI for WOS work "
                            f"{work['UID']}\n")
                    continue

                is_valid_doi = verified_DOI(work_doi, **kwargs)
                if not is_valid_doi:
                    kwargs['output'].write(
                            f"Info: ignoring invalid DOI '{work_doi}' for "
                            f"WOS work {work['UID']}\n")
                    continue

                # insert the work doi and source
                success, new_entry = insert_citation(
                        doi, work_doi, "WoS", **kwargs)
                if not success:
                    kwargs['conn'].rollback()
                    continue

                insert_source(work_doi, doi, "WoS", **kwargs)
                if not inserted_doi_data(doi, publisher, asset_type, **kwargs):
                    kwargs['conn'].rollback()
                    continue

                if kwargs['no_works'] or not new_entry:
                    kwargs['conn'].rollback()
                    continue

                process_work(work_doi, work, doi=doi, **kwargs)
                # roll back any uncommitted changes from process_work() when
                #  the full process fails to complete
                kwargs['conn'].rollback()

            num_records = j['QueryResult']['RecordsFound']
            works_id_params['firstRecord'] += works_id_params['count']

        kwargs['output'].write(
                f"        {num_records} citations found ...\n")
