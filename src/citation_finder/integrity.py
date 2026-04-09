from .utils import db_connect


def run_integrity_checks(**kwargs):
    conn, err = db_connect()
