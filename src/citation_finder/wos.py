import json
import requests

from .local_settings import config


def do_query(**kwargs):
    wos = config['services']['wos']
    api_url = wos['api-url']
    headers = {'X-ApiKey': wos['api-key']}
    params = {'databaseId': "DCI", 'count': 1, 'firstRecord': 1,
              'viewField': "none"}
    for doi, publisher, asset_type in kwargs['doi_list']:
        kwargs['output'].write(
                f"    querying DOI '{doi} | {publisher} | {asset_type}' ...\n")
        # get the WoS ID for the DOI
        params['usrQuery'] = f"DO={doi}"
        response = requests.get(api_url, headers=headers, params=params)
        try:
            j = json.loads(response.text)
        except Exception:
            kwargs['output'].write(
                    f"WoS response for DOI '{doi}' ID is not JSON\n")
            continue

        if (response.status_code == 429 and 'code' in j and j['code'] ==
                "Throttle Error"):
            kwargs['output'].write(
                    "    ***ABORTING due to throttle error\n")
            break

        try:
            response.raise_for_status()
        except Exception as err:
            kwargs['output'].write("HTTP error {} for DOI '{}': '{}'\n".format(
                    response.status_code, doi, err))
            continue

        try:
            wos_id = j['Data']['Records']['records']['REC'][0]['UID']
        except Exception:
            kwargs['output'].write("      No WoS ID found")
            continue

        if len(wos_id) == 0:
            kwargs['output'].write("      Empty WoS ID found")
            continue

        kwargs['output'].write(f"      WoS ID: '{wos_id}'\n")
        # get the WoS IDs for the "works" that have cited this DOI
