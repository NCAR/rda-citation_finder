import json
import os
import requests

from pathlib import Path

from .inserts import insert_citation, insert_source, inserted_doi_data
from .local_settings import config
from .utils import db_connect, reset_new_flag


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

    reset_new_flag(**kwargs)
    kwargs['conn'].close()
