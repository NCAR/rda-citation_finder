from .utils import db_connect


def run_integrity_checks(**kwargs):
    conn, err = db_connect()
    if conn is None:
        err = f"***DATABASE ERROR from run_integrity_checks(): '{err}'"
        raise RuntimeError(err)

    # check for empty titles
    # check author names
    # check for missing authors
    # check for bad publication months
    # print the publisher list
