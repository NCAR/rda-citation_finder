import psycopg2

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


def insert_work_author(pid, author, sequence, source, **kwargs):
    columns = ["id", "id_type", "last_name", "first_name", "middle_name",
               "sequence"]
    values = ["%s"] * len(columns)
    params = [pid['id'], pid['type'], author['family'], author['given'],
              author['middle'], sequence]
    if source == "Open Library" or source == "CrossRef":
        on_conflict = [
                "on conflict on constraint works_authors_pkey do update set "
                "last_name = case when length(excluded.last_name) > length("
                "works_authors.last_name) then excluded.last_name else "
                "works_authors.last_name end, first_name = case when length("
                "excluded.first_name) > length(works_authors.first_name) then "
                "excluded.first_name else works_authors.first_name end, "
                "middle_name = case when length(excluded.middle_name) > "
                "length(works_authors.middle_name) then excluded.middle_name "
                "else works_authors.middle_name end"]

    if 'orcid_id' in author:
        columns.append("orcid_id")
        params.append(author['orcid_id'])
        if 'on_conflict' in locals():
            on_conflict.append(
                    "orcid_id = case when excluded.orcid_id is not null then "
                    "excluded.orcid_id else works_authors.orcid_id end")

    insert = (
            f"insert into {config['citation-database']['schemaname']}."
            f"works_authors ({', '.join[columns]}) values "
            f"({', '.join(values)})")
    if 'on_conflict' in locals():
        insert += ", ".join(on_conflict)

    try:
        cursor = kwargs['conn'].cursor()
        cursor.execute(insert, params)
        kwargs['conn'].commit()
    except psycopg2.errors.UniqueViolation:
        try:
            cursor.execute(
                    "select last_name, first_name, middle_name, orcid_id from "
                    f"{config['citation-database']['schemaname']}."
                    "works_authors where id = %s and id_type = %s and "
                    "sequence = %s", (pid['id'], pid['id_type'], sequence))
            res = cursor.fetchone()
            dupe_mismatch = False
            if (res[0] != author['family'] or res[1] != author['given'] or
                    res[2] != author['middle']):
                dupe_mismatch = True
            elif 'orcid_id' in author and res[3] != author['orcid_id']:
                dupe_mismatch = True

            if dupe_mismatch:
                kwargs['output'].write(
                        f"-##-DUPLICATE AUTHOR MISMATCH ({source}): "
                        f"{pid['type']}: {pid['id']}, last=('{res[0]}'/"
                        f"'{author['family']}'), first=('{res[1]}'/"
                        f"'{author['given']}'), middle=('{res[2]}'/"
                        f"'{author['middle']}')")
                if 'orcid_id' in author:
                    kwargs['output'].write(
                            f", orcid_id=('{res[3]}'/'{author['orcid_id']}')")

                kwargs['output'].write(
                        f", sequence={sequence}\n")

        except Exception as err:
            kwargs['output'].write(
                    f"Error on duplicate author check ('{author['given']} "
                    f"{author['middle']} {author['family']}): '{err}'\n")
    except Exception as err:
        kwargs['output'].write(
                "Error while inserting author ({}): '{}' from {}"
                .format(", ".join(params), err, source))


def insert_journal_work_data(work_doi, pubname, volume, pages, **kwargs):
    try:
        cursor = kwargs['conn'].cursor()
        cursor.execute(
                f"insert into {config['citation-database']['schemaname']}."
                "journal_works (doi, pub_name, volume, pages) values "
                "(%s, %s, %s, %s) on conflict on constraint "
                "journal_works_pkey do update set pub_name = case when "
                "length(excluded.pub_name) > length(journal_works.pub_name) "
                "then excluded.pub_name else journal_works.pub_name end, "
                "volume = case when length(excluded.volume) > length("
                "journal_works.volume) then excluded.volume else "
                "journal_works.volume end, pages = case when length("
                "excluded.pages) > length(journal_works.pages) then excluded."
                "pages else journal_works.pages end",
                (work_doi, pubname, volume, pages))
        kwargs['conn'].commit()
    except Exception as err:
        kwargs['output'].write(
                f"Error while inserting journal data ({work_doi}, {pubname}, "
                f"{volume}, {pages}): '{err}'\n")
