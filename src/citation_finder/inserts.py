from .local_settings import config


def insert_citation(data_doi, works_doi, service, **kwargs):
    try:
        cursor = kwargs['conn'].cursor()
        cursor.execute(
                f"insert into {config['citation-database']['schemaname']}."
                f"{config['doi-groups'][kwargs['doi_group']]['db-table']} "
                "(doi_data, doi_work, new_flag) values (%s, %s, %s) on "
                "conflict (doi_data, doi_work) do nothing",
                (data_doi, works_doi, "1"))
        kwargs['conn'].commit()
        return (True, (cursor.rowcount == 1))
    except Exception as err:
        kwargs['output'].write(
                "Error while inserting {} citation ({}, {}): '{}'\n"
                .format(service, data_doi, works_doi, err))
        return (False, False)


def insert_source(works_doi, data_doi, service, **kwargs):
    try:
        cursor = kwargs['conn'].cursor()
        cursor.execute(
                f"insert into {config['citation-database']['schemaname']}."
                "sources (doi_work, doi_data, source) values (%s, %s, %s) on "
                "conflict on constraint sources_pkey do nothing",
                (works_doi, data_doi, service))
        kwargs['conn'].commit()
    except Exception as err:
        kwargs['output'].write(
                "Error while inserting {} source ({}, {}): '{}'\n"
                .format(service, works_doi, data_doi, err))


def inserted_doi_data(data_doi, publisher, asset_type, **kwargs):
    try:
        cursor = kwargs['conn'].cursor()
        cursor.execute(
                f"insert into {config['citation-database']['schemaname']}."
                "doi_data (doi_data, publisher, asset_type) values "
                "(%s, %s, %s) on conflict on constraint doi_data_pkey do "
                "update set publisher = case when length(excluded.publisher) "
                "> length(doi_data.publisher) then excluded.publisher else "
                "doi_data.publisher end, asset_type = case when length("
                "excluded.asset_type) > length(doi_data.asset_type) then "
                "excluded.asset_type else doi_data.asset_type end",
                (data_doi, publisher, asset_type))
        kwargs['conn'].commit()
        return True
    except Exception as err:
        kwargs['output'].write(
                "Error updating DOI data ({}, {}, {}): '{}'\n"
                .format(data_doi, publisher, asset_type, err))
        return False
