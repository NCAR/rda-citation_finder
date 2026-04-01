import json
import os
import requests
import time

from pathlib import Path

from .inserts import inserted_citation
from .local_settings import config


API_URL = "https://api.eventdata.crossref.org/v1/events"


def find_citations(**kwargs):
    params = {'source': "crossref", 'obj-id': ""}
    for doi, publisher, asset_type in kwargs['doi-list']:
        kwargs['output'].write(
                f"    querying DOI '{doi} | {publisher} | {asset_type}' ...\n")
        filename = (doi.replace("/", "@@") + ".crossref.json")
        filename = os.path.join(config['temporary-directory-path'], filename)
        if os.path.exists(filename):
            with open(filename, "r") as f:
                j = json.load(f)

        else:
            num_tries = 0
            while num_tries < 3:
                time.sleep(num_tries * 5)
                try:
                    params['obj-id'] = doi
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
                        f"Error reading CrossRef JSON for DOI '{doi}' after "
                        "three attempts")
                continue

            if j['status'] != "ok":
                Path(filename).unlink(missing_ok=True)
                kwargs['output'].write(
                        f"Server failure for DOI '{doi}': '{j['message']}")
                continue

            kwargs['output'].write(
                    f"      {len(j['message']['events'])} citations found ...")
            for event in j['message']['events']:
                works_doi = event['subj_id'].replace("\\/", "/")
                works_doi = works_doi.split("doi.org/")[-1]
                if not inserted_citation(doi, works_doi, 'CrossRef', **kwargs):
                    continue


def get_works_data(works_doi):
    cache_file = os.path.join(config['temporary-directory-path'], "cache",
                              works_doi.replace("/", "@@") + ".crossref.json")
    if not os.path.exists(cache_file):
        try:
            response = requests.get(
                    f"https://api.crossref.org/works/{works_doi}")
        except Exception:
            return None

        with open(cache_file, "w") as f:
            f.write(response.text)

    try:
        j = json.load(cache_file)
        return j
    except Exception:
        return None
