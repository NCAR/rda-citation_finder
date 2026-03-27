import json
import psycopg2
import requests

from .local_settings import config


def get_doi_list_from_db(doi_group):
    try:
        db = config['citation-database']
        conn = psycopg2.connect(user=db['user'], password=db['password'],
                                host=db['host'], dbname=db['dbname'])
        cursor = conn.cursor()
        cursor.execute(config['doi-groups'][doi_group]['doi-query']['db'])
        return cursor.fetchall()
    finally:
        if 'conn' in locals():
            conn.close()


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


def get_doi_list_from_api(doi_group):
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

    return list(zip(dois, publishers, asset_types))


def get_doi_list(doi_group):
    if 'db' in config['doi-groups'][doi_group]['doi-query']:
        return get_doi_list_from_db(doi_group)
    elif 'api' in config['doi-groups'][doi_group]['doi-query']:
        return get_doi_list_from_api(doi_group)
    else:
        raise RuntimeError(f"unable to build list of DOIs for {doi_group}")
