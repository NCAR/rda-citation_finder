from .local_settings import config


def get_doi_list_from_db(doi_group):
    doi_list = []
    return doi_list


def get_doi_list_from_api(doi_group):
    doi_list = []
    return doi_list


def get_doi_list(doi_group):
    if 'db' in config['doi-groups'][doi_group]['doi-query']:
        return get_doi_list_from_db(doi_group)
    elif 'api' in config['doi-groups'][doi_group]['doi-query']:
        return get_doi_list_from_api(doi_group)
    else:
        raise RuntimeError(f"unable to build list of DOIs for {doi_group}")
