import json
import os
import psycopg2
import requests

from pathlib import Path

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
        #kwargs['conn'].commit()
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
        #kwargs['conn'].commit()
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
        #kwargs['conn'].commit()
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
              author['middle'], str(sequence)]
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
        values.append("%s")
        params.append(author['orcid_id'])
        if 'on_conflict' in locals():
            on_conflict.append(
                    "orcid_id = case when excluded.orcid_id is not null then "
                    "excluded.orcid_id else works_authors.orcid_id end")

    insert = (
            f"insert into {config['citation-database']['schemaname']}."
            f"works_authors ({', '.join(columns)}) values "
            f"({', '.join(values)})")
    if 'on_conflict' in locals():
        insert += ", ".join(on_conflict)

    try:
        cursor = kwargs['conn'].cursor()
        cursor.execute(insert, params)
        #kwargs['conn'].commit()
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
                "Error while inserting author ({}): '{}' from {}\n"
                .format(", ".join(params), err, source))


def insert_book_chapter_work_data(work_doi, isbn, pages, **kwargs):
    try:
        cursor = kwargs['conn'].cursor()
        cursor.execute(
                f"insert into {config['citation-database']['schemaname']}."
                "book_chapter_works (doi, pages, isbn) values (%s, %s, %s) "
                "on conflict on constraint book_chapter_works_pkey do update "
                "set pages = case when length(excluded.pages) > length("
                "book_chapter_works.pages) then excluded.pages else "
                "book_chapter_works.pages end, isbn = case when length("
                "excluded.isbn) > length(book_chapter_works.isbn) then "
                "excluded.isbn else book_chapter_works.isbn end",
                (work_doi, pages, isbn))
        #kwargs['conn'].commit()
    except Exception as err:
        kwargs['output'].write(
                f"Error while inserting book chapter data ({work_doi}, "
                f"{isbn}, {pages}): '{err}'\n")


def get_open_library_book_json(isbn):
    cache_file = os.path.join(config['temporary-directory-path'],
                              "citation_cache",
                              isbn + ".openlibrary.json")
    if not os.path.exists(cache_file):
        try:
            response = requests.get(
                    "https://openlibrary.org/api/books?bibkeys="
                    f"ISBN:{isbn}&jscmd=details&format=json")
            with open(cache_file, "w") as f:
                f.write(response.text)

        except Exception as err:
            Path(cache_file).unlink(missing_ok=True)
            raise RuntimeError(f"openlibrary error: '{err}'")

    try:
        with open(cache_file, "r") as f:
            j = json.load(f)

        if len(j) == 0:
            Path(cache_file).unlink(missing_ok=True)
            raise RuntimeError("no data available from Open Library")

    except Exception as err:
        raise RuntimeError(f"cache file '{cache_file}' open error: '{err}'")

    return j


def get_google_books_json(isbn):
    cache_file = os.path.join(config['temporary-directory-path'],
                              "citation_cache",
                              isbn + ".googlebooks.json")
    if not os.path.exists(cache_file):
        try:
            response = requests.get(
                    f"https://www.googleapis.com/books/v1/volumes?q=isbn{isbn}"
                    f"&key={config['google-books-api-key']}")
            with open(cache_file, "w") as f:
                f.write(response.text)

        except Exception as err:
            Path(cache_file).unlink(missing_ok=True)
            raise RuntimeError(f"google books error: '{err}'")

    try:
        with open(cache_file, "r") as f:
            j = json.load(f)

        if j['totalItems'] == 0:
            Path(cache_file).unlink(missing_ok=True)
            raise RuntimeError("no data available from Google Books")

    except Exception as err:
        raise RuntimeError(f"cache file '{cache_file}' open error: '{err}'")

    return j


def insert_book_work_data(isbn, **kwargs):
    try:
        j = get_open_library_book_json(isbn)
        details = j['ISBN:'+isbn]['details']
        authors = []
        if 'authors' not in details:
            if ('by_statement' not in details or
                    details['by_statement'].find("edited by ") != 0):
                raise RuntimeError(
                        f"Missing Open Library author(s) for ISBN: '{isbn}'")

            authors.append({'given': None, 'middle': "", 'family': None})
            parts = details['by_statement'][10:].split()
            if parts[-1][-1] == ".":
                parts[-1] = parts[-1][0:-1]

            if parts[0].count(".") > 1:
                parts0 = parts[0].split(".")
                if len(parts0[-1]) == 0:
                    del parts0[-1]

                authors[-1]['given'] = parts0[0] + "."
                authors[-1]['middle'] = ". ".join(parts0[1:]) + "."
            else:
                authors[-1]['given'] = parts[0]
                del parts[0]
                if len(parts) > 1:
                    authors[-1]['middle'] = parts[0]
                    del parts[0]

            authors[-1]['family'] = " ".join(parts)
        else:
            for author in details['authors']:
                authors.append({'given': None, 'middle': "", 'family': None})
                parts = author['name'].split()
                authors[-1]['given'] = parts[0]
                del parts[0]
                if len(parts) > 1:
                    authors[-1]['middle'] = parts[0]
                    del parts[0]

                authors[-1]['family'] = " ".join(parts)

        pid = {'id': isbn, 'type': "ISBN"}
        for sequence, author in enumerate(authors):
            insert_work_author(pid, author, sequence, "Open Library", **kwargs)

        cursor = kwargs['conn'].cursor()
        cursor.execute(
                f"insert into {config['citation-database']['schemaname']}."
                "book_works (isbn, title, publisher) values (%s, %s, %s) on "
                "conflict on constraint book_works_pkey do update set title = "
                "case when length(excluded.title) > length(book_works.title) "
                "then excluded.title else book_works.title end, publisher = "
                "case when length(excluded.publisher) > length(book_works."
                "publisher) then excluded.publisher else book_works.publisher "
                "end", (isbn, details['title'], details['publishers'][0]))
    except Exception:
        try:
            j = get_google_books_json(isbn)
            vinfo = j['items'][0]['volumeInfo']
            authors = []
            for author in vinfo['authors']:
                authors.append({'given': None, 'middle': "", 'family': None})
                parts = author.split()
                authors[-1]['given'] = parts[0]
                del parts[0]
                if len(parts) > 1:
                    authors[-1]['middle'] = parts[0]
                    del parts[0]

                authors[-1]['family'] = " ".join(parts)

            pid = {'id': isbn, 'type': "ISBN"}
            for sequence, author in enumerate(authors):
                insert_work_author(pid, author, sequence, "Google Books",
                                   **kwargs)

            cursor = kwargs['conn'].cursor()
            cursor.execute(
                    f"insert into {config['citation-database']['schemaname']}."
                    "book_works (isbn, title, publisher) values (%s, %s, %s) "
                    "on conflict on constraint book_works_pkey do update set "
                    "title = case when length(excluded.title) > length("
                    "book_works.title) then excluded.title else book_works."
                    "title end, publisher = case when length(excluded."
                    "publisher) > length(book_works.publisher) then excluded."
                    "publisher else book_works.publisher end",
                    (isbn, vinfo['title'].replace("\\", "\\\\"),
                     vinfo['publisher']))
        except Exception as err:
            kwargs['output'].write(
                    f"Error while inserting book data ({isbn}): '{err}'\n")


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
        #kwargs['conn'].commit()
    except Exception as err:
        kwargs['output'].write(
                f"Error while inserting journal data ({work_doi}, {pubname}, "
                f"{volume}, {pages}): '{err}'\n")


def insert_proceedings_work_data(work_doi, pubname, volume, pages, **kwargs):
    try:
        cursor = kwargs['conn'].cursor()
        cursor.execute(
                f"insert into {config['citation-database']['schemaname']}."
                "proceedings_works (doi, pub_name, volume, pages) values "
                "(%s, %s, %s, %s) on conflict on constraint "
                "proceedings_works_pkey do update set pub_name = case when "
                "length(excluded.pub_name) > length("
                "proceedings_works.pub_name) then excluded.pub_name else "
                "proceedings_works.pub_name end, volume = case when length("
                "excluded.volume) > length(proceedings_works.volume) then "
                "excluded.volume else proceedings_works.volume end, pages = "
                "case when length(excluded.pages) > length(proceedings_works."
                "pages) then excluded.pages else proceedings_works.pages end",
                (work_doi, pubname, volume, pages))
        #kwargs['conn'].commit()
    except Exception as err:
        kwargs['output'].write(
                f"Error while inserting proceedings data ({work_doi}, "
                f"{pubname}, {volume}, {pages}): '{err}'\n")


def insert_general_work_data(work_doi, title, pubdate, pubtype, publisher,
                             **kwargs):
    title = title.replace('\\\\"', '"')
    title = title.replace('\\"', '"')
    try:
        cursor = kwargs['conn'].cursor()
        cursor.execute(
                f"insert into {config['citation-database']['schemaname']}."
                "works (doi, title, pub_year, type, publisher, pub_month) "
                "values (%s, %s, %s, %s, %s, %s) on conflict on constraint "
                "works_pkey do update set title = case when length(excluded."
                "title) > length(works.title) then excluded.title else works."
                "title end, publisher = case when length(excluded.publisher) "
                "> length(works.publisher) then excluded.publisher else works."
                "publisher end",
                (work_doi, title, pubdate['year'], pubtype, publisher,
                 pubdate['month']))
        #kwargs['conn'].commit()
    except Exception as err:
        kwargs['output'].write(
                f"Error while inserting general work data ({work_doi}, "
                f"{title}, {pubdate}, {pubtype}, {publisher}): '{err}'\n")
