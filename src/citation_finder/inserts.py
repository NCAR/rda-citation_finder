import psycopg2

from .local_settings import config


def insert_citation(doi, works_doi, service, **kwargs):
    try:
        db = config['citation-database']
        conn = psycopg2.connect(user=db['user'], password=db['password'],
                                host=db['host'], dbname=db['dbname'])
        cursor = conn.cursor()
        cursor.execute(
                f"insert into {db['schemaname']}."
                f"{config['doi-groups'][kwargs['doi_group']]['db-table']} "
                "(doi_data, doi_work, new_flag) values (%s, %s, %s) on "
                "conflict (doi_data, doi_work) do nothing",
                (doi, works_doi, "1"))
        conn.commit()
        return (True, (cursor.rowcount == 1))
    except Exception as err:
        kwargs['output'].write(
                "Error while inserting {} citation ({}, {}): '{}'\n"
                .format(service, doi, works_doi, err))
        return (False, False)
