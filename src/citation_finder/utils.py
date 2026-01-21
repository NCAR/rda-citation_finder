def convert_unicodes(s):
    s = (s.replace(r"\u00a0", " ")
          .replace(r"\u2010", "-")
          .replace(r"\u2013", "-")
          .replace(r"\u2014", "-")
          .replace(r"\u2019", "'"))
    return s


def unicode_escape(s):
    escaped_string = ""
    escaped = False
    for c in s:
        code = ord(c)
        if code < 0x80:
            escaped_string += c
        elif code < 0xff:
            escaped_string += fr"\u00{code:02x}"
            escaped = True
        else:
            escaped_string += fr"\u{code:04x}"
            escaped = True

    if escaped:
        return convert_unicodes(escaped_string)

    return escaped_string


def add_authors_to_db(author_list, ident, db_conn):
    cursor = db_conn.cursor()
    id, id_type = ident
    seqno = 0
    do_commit = False
    for author in author_list:
        if (((id_type == "DOI" and author['creatorType'] == "author") or
                (id_type == "ISBN" and author['creatorType'] == "editor"))
                and 'lastName' in author and len(author['lastName']) > 0):
            parts = author['firstName'].split()
            fname = unicode_escape(parts[0])
            if len(parts) > 1:
                mname = unicode_escape(parts[1])
            else:
                mname = ""

            do_commit = True
            cursor.execute((
                    "insert into citation.works_authors values (%s, %s, %s, "
                    "%s, %s, NULL, %s) on conflict do nothing"),
                    (id, id_type, unicode_escape(author['lastName']),
                     fname, mname, seqno))
            seqno += 1

    if (do_commit):
        db_conn.commit()
    else:
        print("*** NO INSERTABLE AUTHORS for '{}'".format(ident))


def inserted_book_works_data(works_data, db_conn, service) -> bool:
    try:
        cursor = db_conn.cursor()
        cursor.execute((
            "insert into citation.book_works (isbn, title, publisher) values "
            "(%s, %s, %s) on conflict on constraint book_works_pkey do update "
            "set title = case when length(excluded.title) > length(book_works."
            "title) then excluded.title else book_works.title end, publisher "
            "= case when length(excluded.publisher) > length(book_works."
            "publisher) then excluded.publisher else book_works.publisher "
            "end"),
            (works_data['ISBN'], works_data['bookTitle'],
             works_data['publisher']))
        db_conn.commit()
    except Exception as err:
        print("Error while inserting {} book data ({}, {}, {}): '{}'"
              .format(service, works_data['ISBN'], works_data['bookTitle'],
                      works_data['publisher'], str(err)))
        return False

    return True


def inserted_book_chapter_works_data(works_data, db_conn, service) -> bool:
    try:
        cursor = db_conn.cursor()
        add_authors_to_db(works_data['creators'], (works_data['ISBN'], "ISBN"),
                          db_conn)
        cursor.execute((
            "insert into citation.book_chapter_works (doi, pages, isbn) "
            "values (%s, %s, %s) on conflict on constraint "
            "book_chapter_works_pkey do update set pages = case when length("
            "excluded.pages) > length(book_chapter_works.pages) then excluded."
            "pages else book_chapter_works.pages end, isbn = case when length("
            "excluded.isbn) > length(book_chapter_works.isbn) then excluded."
            "isbn else book_chapter_works.isbn end"),
            (works_data['DOI'], works_data['pages'], works_data['ISBN']))
        db_conn.commit()
        if not inserted_book_works_data(works_data, db_conn, service):
            return False

    except Exception as err:
        print("Error while inserting {} book chapter data ({}, {}, {}): '{}'"
              .format(service, works_data['DOI'], works_data['pages'],
                      works_data['ISBN'], str(err)))
        return False

    return True


def inserted_journal_works_data(works_data, db_conn, service) -> bool:
    volume = works_data['volume'] + "(" + works_data['issue'] + ")"
    try:
        cursor = db_conn.cursor()
        cursor.execute((
                "insert into citation.journal_works (doi, pub_name, volume, "
                "pages) values (%s, %s, %s, %s) on conflict on constraint "
                "journal_works_pkey do update set pub_name = case when length("
                "excluded.pub_name) > length(journal_works.pub_name) then "
                "excluded.pub_name else journal_works.pub_name end, volume = "
                "case when length(excluded.volume) > length(journal_works."
                "volume) then excluded.volume else journal_works.volume end, "
                "pages = case when length(excluded.pages) > length("
                "journal_works.pages) then excluded.pages else journal_works."
                "pages end"), (works_data['DOI'],
                               works_data['publicationTitle'],
                               volume,
                               works_data['pages']))
        db_conn.commit()
    except Exception as err:
        print("Error while inserting {} journal data ({}, {}, {}, {}): '{}'"
              .format(service, works_data['DOI'],
                      works_data['publicationTitle'], volume,
                      works_data['pages'], str(err)))
        return False

    return True


def inserted_general_works_data(works_data, db_conn, work_type,
                                service) -> bool:
    try:
        cursor = db_conn.cursor()
        cursor.execute((
                "insert into citation.works (doi, title, pub_year, type, "
                "publisher, pub_month) values (%s, %s, %s, %s, %s, %s) on "
                "conflict on constraint works_pkey do update set title = case "
                "when length(excluded.title) > length(works.title) then "
                "excluded.title else works.title end, publisher = case when "
                "length(excluded.publisher) > length(works.publisher) then "
                "excluded.publisher else works.publisher end"),
                (works_data['DOI'], works_data['title'],
                 works_data['date'][0:4], works_data['date'][5:7], work_type,
                 works_data['libraryCatalog']))
    except Exception as err:
        print("Error while inserting {} work ({}, {}, {}, {}, {}, {}): '{}'"
              .format(service, works_data['DOI'], works_data['title'],
                      works_data['date'][0:4], works_data['date'][5:7],
                      work_type, works_data['libraryCatalog'], str(err)))

    return True


def inserted_citation(data_doi, insert_table, db_conn, service) -> bool:
    return True


def insert_source(data_doi, db_conn, service):
    pass
