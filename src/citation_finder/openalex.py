import json
import os
import requests

from pathlib import Path

from .inserts import (insert_citation, insert_source, inserted_doi_data)
from .local_settings import config
from .utils import db_connect, verified_DOI


API_URL = "https://api.openalex.org/works"


def find_citations(**kwargs):
    kwargs['conn'], err = db_connect()
    if kwargs['conn'] is None:
        err = f"***DATABASE ERROR from crossref.find_citations(): '{err}'"
        raise RuntimeError(err)

    for doi, publisher, asset_type in kwargs['doi_list']:
        kwargs['output'].write(
                f"    querying DOI '{doi} | {publisher} | {asset_type}' ...\n")
        # get the OpenAlex ID for the DOI
        filename = doi.replace("/", "@@") + ".openalex_id.json"
        filename = os.path.join(config['temporary-directory-path'], filename)
        if os.path.exists(filename):
            with open(filename, "r") as f:
                j = json.load(f)

        else:
            try:
                response = requests.get(
                        f"{API_URL}/https://doi.org/{doi}?select=id&api_key="
                        f"{config['services']['openalex']['api-key']}")
                j = json.loads(response.text)
                with open(filename, "w") as f:
                    f.write(response.text)

            except Exception:
                Path(filename).unlink(missing_ok=True)
                kwargs['output'].write(
                        f"Error reading DataCITE JSON for DOI '{doi}'\n")
                continue

        if 'id' not in j:
            continue

        openalex_id = j['id']
        kwargs['output'].write(f"      OpenAlex ID: '{openalex_id}'\n")
        # get the DOIs of the citing works
        params = {'per_page': 100, 'page': 1,
                  'filter': (
                          f"cites:{openalex_id},type:book-chapter|article|"
                          "preprint"),
                  'select': "doi",
                  'api_key': config['services']['openalex']['api-key']}
        count = 0x7fffffff
        num_results = 0
        while num_results < count:
            count = 0
            filename = (doi.replace("/", "@@") + ".openalex." +
                        str(params['page']) + ".json")
            filename = os.path.join(config['temporary-directory-path'],
                                    filename)
            if os.path.exists(filename):
                with open(filename, "r") as f:
                    j = json.load(f)

            else:
                try:
                    response = requests.get(API_URL, params=params)
                    j = json.loads(response.text)
                    with open(filename, "w") as f:
                        f.write(response.text)

                except Exception:
                    Path(filename).unlink(missing_ok=True)
                    kwargs['output'].write(
                            f"Error reading OpenAlex JSON for DOI '{doi}'\n")
                    continue

            if 'meta' not in j or 'results' not in j:
                continue

            if count == 0:
                count = j['meta']['count']
                kwargs['output'].write(f"      {count} citations found ...\n")

            num_results += len(j['results'])
            for result in j['results']:
                work_doi = result['doi'].replace("https://doi.org/", "")
                is_valid_doi = verified_DOI(work_doi, **kwargs)
                if not is_valid_doi:
                    kwargs['output'].write(
                            f"Info: ignoring invalid DOI '{work_doi}'\n")
                    continue

                success, new_entry = insert_citation(
                        doi, work_doi, "OpenAlex", **kwargs)
                if not success:
                    continue

                insert_source(work_doi, doi, "OpenAlex", **kwargs)
                if not inserted_doi_data(doi, publisher, asset_type, **kwargs):
                    continue

                if kwargs['no_works'] or not new_entry:
                    continue

                print(f"NEW CITATION! {work_doi}")
                kwargs['output'].write(f"NEW CITATION! {work_doi}\n")

            params['page'] += 1

    kwargs['conn'].close()
