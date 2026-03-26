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
        return [e[0] for e in cursor.fetchall()]
    finally:
        if 'conn' in locals():
            conn.close()


def get_doi_list_from_api(doi_group):
    doi_list = []
    api = config['doi-groups'][doi_group]['doi-query']['api']
    base_url = api['url']
    doi_response = api['response']['doi'].split(".")
    if doi_response[0] == "$":
        del doi_response[0]
    else:
        raise ValueError(
                f"'{api['response']['doi']}' is not a valid JSON path")

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
        o = json.loads(response.text)
        for x in range(0, len(doi_response)):
            if doi_response[x].endswith("[*]"):
                for entry in o[doi_response[x][:-3]]:
                    for y in range(x+1, len(doi_response)):
                        entry = entry[doi_response[y]]

                    doi_list.append(entry)

                break

            else:
                o = o[doi_response[x]]

        if len(doi_list) == 0:
            doi_list.append(o)

    return doi_list


def get_doi_list(doi_group):
    if 'db' in config['doi-groups'][doi_group]['doi-query']:
        return get_doi_list_from_db(doi_group)
    elif 'api' in config['doi-groups'][doi_group]['doi-query']:
        return get_doi_list_from_api(doi_group)
    else:
        raise RuntimeError(f"unable to build list of DOIs for {doi_group}")
