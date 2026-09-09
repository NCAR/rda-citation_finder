import json
import jsonpath_ng
import requests

from .local_settings import config
from .utils import db_connect


def get_doi_list_from_db(doi_group, **kwargs):
    kwargs['output'].write("    filling list from a database ...\n")
    conn, err = db_connect()
    if conn is None:
        return []

    cursor = conn.cursor()
    cursor.execute(config['doi-groups'][doi_group]['doi-query']['db'])
    doi_list = cursor.fetchall()
    conn.close()
    kwargs['output'].write(
            f"    ... found {len(doi_list)} DOIs.\n")
    return doi_list


def get_doi_list_from_api(doi_group, **kwargs):
    kwargs['output'].write("    filling list from an api ...\n")
    api = config['doi-groups'][doi_group]['doi-query']['api']
    base_url = api['url']
    dois = []
    publishers = []
    asset_types = []
    page_count = 1
    page_number = 1
    while page_number <= page_count:
        url = base_url
        if 'pagination' in api and 'page-number' in api['pagination']:
            if url.find("?") < 0:
                url += "?"
            else:
                url += "&"

            url += f"{api['pagination']['page-number']}={page_number}"
            page_number += 1
            if 'page-size' in api['pagination']:
                url += f"&{api['pagination']['page-size']}"

        print(url)
        response = requests.get(url)
        dois.extend([e.value for e in jsonpath_ng.parse(api['response']['doi'])
                     .find(response.json())])
        publishers.extend([e.value for e in
                           jsonpath_ng.parse(api['response']['publisher'])
                           .find(response.json())])
        asset_types.extend([e.value.lower() for e in
                            jsonpath_ng.parse(api['response']['asset-type'])
                            .find(response.json())])

        if 'pagination' in api and 'page-count' in api['pagination']:
            page_count = (
                    jsonpath_ng.parse(api['pagination']['page-count'])
                    .find(response.json())[0].value)

    doi_list = list(zip(dois, publishers, asset_types))
    kwargs['output'].write(f"    ... found {len(doi_list)} DOIs.\n")
    return doi_list


def get_doi_list(doi_group, **kwargs):
    kwargs['output'].write(f"Filling list of DOIs for '{doi_group}' ...\n")
    if 'db' in config['doi-groups'][doi_group]['doi-query']:
        doi_list = get_doi_list_from_db(doi_group, **kwargs)
    elif 'api' in config['doi-groups'][doi_group]['doi-query']:
        doi_list = get_doi_list_from_api(doi_group, **kwargs)
    else:
        raise RuntimeError(f"unable to build list of DOIs for {doi_group}")

    kwargs['output'].write("... done filling DOI list.\n")
    return doi_list
