import json
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


def json_parse(response, json_path):
    nodes = json_path.split(".")
    if nodes[0] == "$":
        del nodes[0]
    else:
        raise ValueError(f"'{json_path}' is not a valid JSON path")

    vals = []
    o = json.loads(response.text)
    for x in range(0, len(nodes)):
        if nodes[x].endswith("[*]"):
            for entry in o[nodes[x][:-3]]:
                for y in range(x+1, len(nodes)):
                    entry = entry[nodes[y]]

                vals.append(entry)

            break

        else:
            o = o[nodes[x]]

    if len(vals) == 0:
        vals.append(o)

    return vals


def get_doi_list_from_api(doi_group, **kwargs):
    kwargs['output'].write("    filling list from a database ...\n")
    api = config['doi-groups'][doi_group]['doi-query']['api']
    base_url = api['url']
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

        print(url)
        response = requests.get(url)
        dois = json_parse(response, api['response']['doi'])
        publishers = json_parse(response, api['response']['publisher'])
        asset_types = json_parse(response, api['response']['asset-type'])

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
