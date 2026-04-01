import json
import os
import requests

from .local_settings import config


API_URL = "https://api.eventdata.crossref.org/v1/events"


def find_citations(**kwargs):
    pass


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
