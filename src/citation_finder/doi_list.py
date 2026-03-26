import psycopg2

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
    return doi_list


def get_doi_list(doi_group):
    if 'db' in config['doi-groups'][doi_group]['doi-query']:
        return get_doi_list_from_db(doi_group)
    elif 'api' in config['doi-groups'][doi_group]['doi-query']:
        return get_doi_list_from_api(doi_group)
    else:
        raise RuntimeError(f"unable to build list of DOIs for {doi_group}")
