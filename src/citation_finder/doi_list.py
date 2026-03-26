from .local_settings import config


def get_doi_list(doi_group):
    if 'db' in config['doi-groups'][doi_group]['doi-query']:
        pass
    elif 'api' in config['doi-groups'][doi_group]['doi-query']:
        pass
    else:
        raise RuntimeError(f"unable to build list of DOIs for {doi_group}")
