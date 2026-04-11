from datetime import datetime

from .utils import db_connect


def run_integrity_checks(**kwargs):
    conn, err = db_connect()
    if conn is None:
        err = f"***DATABASE ERROR from run_integrity_checks(): '{err}'"
        raise RuntimeError(err)

    cursor = conn.cursor()
    # check for work DOIs without an entry
    try:
        cursor.execute(
                "select s.doi_work, s.sources from (select distinct doi_work, "
                "string_agg(distinct source, ',') as sources from "
                f"{kwargs['schemaname']}.sources group by doi_work) as s left "
                f"join {kwargs['schemaname']}.works as w on w.doi = s."
                "doi_work where w.doi is null order by s.sources")
        res = cursor.fetchall()
        kwargs['mail_message'].write(
                f"  # works without an entry: {len(res)}\n"
                "    Works DOI list:\n")
        for e in res:
            kwargs['mail_message'].write(f"      {e[0]:<50} {e[1]}\n")

    except Exception as err:
        kwargs['mail_message'].write(
                f"  **Error checking for works without an entry: '{err}'\n")

    # check for empty titles
    try:
        cursor.execute(
                f"select * from {kwargs['schemaname']}.works where title = ''")
        kwargs['mail_message'].write(
                f"  # works without a title: {len(cursor.fetchall())}\n")
    except Exception as err:
        kwargs['mail_message'].write(
                f"  **Error checking for empty titles: '{err}'\n")

    # check author names
    try:
        cursor.execute(
                f"select * from {kwargs['schemaname']}.works_authors where "
                "last_name like '%\\\\-%'")
        kwargs['mail_message'].write(
                "  # author last names with an escaped hyphen: "
                f"{len(cursor.fetchall())}\n")
    except Exception as err:
        kwargs['mail_message'].write(
                "  **Error checking for author last names with escaped "
                f"hyphen: '{err}'\n")

    try:
        cursor.execute(
                f"select * from {kwargs['schemaname']}.works_authors where "
                "last_name like '%\\\\''%'")
        kwargs['mail_message'].write(
                "  # author last names with an escaped apostrophe: "
                f"{len(cursor.fetchall())}\n")
    except Exception as err:
        kwargs['mail_message'].write(
                "  **Error checking for author last names with escaped "
                f"apostrophe: '{err}'\n")

    # check for missing authors
    try:
        cursor.execute(
                "select w.doi, count(a.last_name) from "
                f"{kwargs['schemaname']}.works as w left join "
                f"{kwargs['schemaname']}.works_authors as a on a.id = w.doi "
                "group by w.doi having count(a.last_name) = 0")
        res = cursor.fetchall()
        kwargs['mail_message'].write(
                f"  # of DOIs with missing authors: {len(res)}\n"
                "    DOI list:\n")
        for e in res:
            kwargs['mail_message'].write(f"      {e[0]}\n")

    except Exception as err:
        kwargs['mail_message'].write(
                  f"**Error checking for missing authors: '{err}'\n")

    # check for missing publication months
    try:
        cursor.execute(
                f"select * from {kwargs['schemaname']}.works where pub_month "
                "= 0")
        res = cursor.fetchall()
        kwargs['mail_message'].write(
                f"  # works without a publication month: {len(res)}\n"
                "   Work DOI list:\n")
        for e in res:
            kwargs['mail_message'].write(f"      {e[0]}\n")

    except Exception as err:
        kwargs['mail_message'].write(
                f"  **Error checking for missing publication months: '{err}'"
                "\n")

    curr_yrmo = datetime.now().strftime("%Y%m")
    try:
        cursor.execute(
                f"select * from {kwargs['schemaname']}.works where "
                "pub_year*100+pub_month > %s", (curr_yrmo, ))
        kwargs['mail_message'].write(
                "  # works with a future publication month: "
                f"{len(cursor.fetchall())}\n")
    except Exception as err:
        kwargs['mail_message'].write(
                f"  **Error checking for future publication months: '{err}'\n")
    # print the publisher list
    try:
        cursor.execute(
                f"select distinct publisher from {kwargs['schemaname']}.works")
        res = cursor.fetchall()
        kwargs['mail_message'].write("Current Publisher List:\n")
        for e in res:
            kwargs['mail_message'].write(f"Publisher: '{e[0]}'\n")

    except Exception as err:
        kwargs['mail_message'].write(
                "  **Error getting list of pubishers from 'works' table: "
                f"'{err}'\n")
