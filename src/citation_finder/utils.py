import psycopg2
import requests

from .local_settings import config


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


def repair_string(s):
    parts = s.split("\\n")
    if len(parts) > 1:
        parts = [e.strip() for e in parts]
        s = " ".join(parts)

    return s.replace("\\/", "/").replace("\\", "\\\\")


def db_connect():
    try:
        conn = psycopg2.connect(
                user=config['citation-database']['user'],
                password=config['citation-database']['password'],
                host=config['citation-database']['host'],
                dbname=config['citation-database']['dbname'])
        return (conn, None)
    except Exception as err:
        return (None, err)


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


def regenerate_dataset_descriptions(**kwargs):
    try:
        cursor = kwargs['conn'].cursor()
        cursor.execute(
                "select v.dsid, count(c.new_flag) from "
                f"{config['citation-database']['schemaname']}."
                f"{config['doi-groups'][kwargs['doi_group']]['db-table']} as "
                "c left join (select distinct dsid, doi from dssdb.dsvrsn) as "
                "v on v.doi ilike c.doi_data where c.new_flag = '1' group by "
                "v.dsid")
        res = cursor.fetchall()
        for e in res:
            msg = (f"Found {e[1]} new {kwargs['service']} data citations for "
                   f"{e[0]}\n")
            kwargs['output'].write(msg)
            kwargs['mail_message'].write(msg)
            try:
                response = requests.get(
                        f"https://gdex.ucar.edu/redeploy/dsgen{e[0]}")
                response.raise_for_status()
            except Exception as err:
                kwargs['output'].write(
                        f"Error while regenerating {e[0]} (service: "
                        f"{kwargs['service']}): '{err}'\n")

    except Exception as err:
        kwargs['output'].write(
                f"Error while obtaining list of new {kwargs['service']} "
                f"citations: '{err}'\n")


def reset_new_flag(**kwargs):
    try:
        cursor = kwargs['conn'].cursor()
        cursor.execute(
                f"update {config['citation-database']['schemaname']}."
                f"{config['doi-groups'][kwargs['doi_group']]['db-table']} set "
                "new_flag = '0' where new_flag = '1'")
        kwargs['conn'].commit()
    except Exception as err:
        kwargs['output'].write(
                f"Error updating 'new_flag' in "
                f"{config['citation-database']['schemaname']}."
                f"{config['doi-groups'][kwargs['doi_group']]['db-table']}: "
                f"'{err}'\n")
