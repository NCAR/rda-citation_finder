import psycopg2

from .local_settings import config


def insert_citation(data_doi, works_doi, service, **kwargs):
    try:
        cursor = kwargs['conn'].cursor()
        cursor.execute(
                f"insert into {db['schemaname']}."
                f"{config['doi-groups'][kwargs['doi_group']]['db-table']} "
                "(doi_data, doi_work, new_flag) values (%s, %s, %s) on "
                "conflict (doi_data, doi_work) do nothing",
                (data_doi, works_doi, "1"))
        conn.commit()
        return (True, (cursor.rowcount == 1))
    except Exception as err:
        kwargs['output'].write(
                "Error while inserting {} citation ({}, {}): '{}'\n"
                .format(service, data_doi, works_doi, err))
        return (False, False)


def insert_source(works_doi, data_doi, service, **kwargs):
    pass
