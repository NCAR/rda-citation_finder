import json
import os
import requests

from pathlib import Path

from .crossref import get_work_data as get_crossref_work_data
from .crossref import get_publication_date as get_crossref_publication_date
from .crossref import insert_authors as insert_crossref_authors
from .crossref import (
        insert_publication_data as insert_crossref_publication_data)
from .inserts import (insert_citation, insert_general_work_data, insert_source,
                      inserted_doi_data)
from .local_settings import config
from .utils import (convert_unicodes, db_connect, reset_new_flag,
                    regenerate_dataset_descriptions, repair_string,
                    verified_DOI)


API_URL = "https://api.datacite.org/dois"


def find_citations(**kwargs):
    kwargs['conn'], err = db_connect()
    if kwargs['conn'] is None:
        err = f"***DATABASE ERROR from crossref.find_citations(): '{err}'"
        raise RuntimeError(err)

    for doi, publisher, asset_type in kwargs['doi_list']:
        kwargs['output'].write(
                f"    querying DOI '{doi} | {publisher} | {asset_type}' ...\n")
        filename = doi.replace("/", "@@") + ".datacite.json"
        filename = os.path.join(config['temporary-directory-path'], filename)
        if os.path.exists(filename):
            with open(filename, "r") as f:
                j = json.load(f)

        else:
            try:
                response = requests.get(f"{API_URL}/{doi}")
                j = json.loads(response.text)
                with open(filename, "w") as f:
                    f.write(response.text)

            except Exception:
                Path(filename).unlink(missing_ok=True)
                kwargs['output'].write(
                        f"Error reading DataCITE JSON for DOI '{doi}'\n")
                continue

        if 'relationships' not in j['data']:
            continue

        j = j['data']['relationships']
        if 'citations' not in j:
            continue

        j = j['citations']
        kwargs['output'].write(f"      {len(j['data'])} citations found ...\n")
        for work_doi in j['data']:
            is_valid_doi = verified_DOI(work_doi)
            if not is_valid_doi:
                kwargs['output'].write(
                        f"Info: ignoring invalid DOI '{work_doi}'\n")
                continue

            work_doi = work_doi['id']
            success, new_entry = insert_citation(
                    doi, work_doi, "DataCite", **kwargs)
            if not success:
                continue

            insert_source(work_doi, doi, "DataCite", **kwargs)
            if not inserted_doi_data(doi, publisher, asset_type, **kwargs):
                continue

            if kwargs['no_works'] or not new_entry:
                continue

            work_data = get_crossref_work_data(work_doi)
            if work_data is None:
                kwargs['output'].write(
                        "***Unable to get CrossRef data for works DOI "
                        f"'{work_doi}'\n")
                continue

            # add author data for the citing work
            insert_crossref_authors(work_data, **kwargs)
            # add type-specific data for the work
            pubtype = insert_crossref_publication_data(work_data, **kwargs)
            if pubtype is None:
                continue

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
                            f"work DOI {work_doi} citing {doi}\n")
            else:
                kwargs['output'].write(
                        f"***NO OR BAD PUBLISHER DATE for work DOI {work_doi} "
                        f"citing {doi}\n")

    if kwargs['doi_group'] == "rda":
        regenerate_dataset_descriptions(service="DataCite", **kwargs)

    reset_new_flag(**kwargs)
    kwargs['conn'].close()
