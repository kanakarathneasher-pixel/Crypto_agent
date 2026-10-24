"""Read-only sandbox response check. Static fixtures are not trading evidence."""
import requests
from backend.coinbase_execution import SANDBOX, PREFIX, normalize_order


def check():
    with requests.Session() as session:
        response = session.get(SANDBOX+PREFIX+'/orders/historical/batch', timeout=(5, 20))
        response.raise_for_status()
        orders = response.json()['orders']
        for order in orders:
            parsed = normalize_order(order, [])
            assert parsed['state'] in ('UNKNOWN', 'ACCEPTED', 'FILLED', 'CANCELLED', 'REJECTED', 'CANCEL_PENDING')
        accounts = session.get(SANDBOX+PREFIX+'/accounts', timeout=(5, 20))
        accounts.raise_for_status()
        assert isinstance(accounts.json()['accounts'], list)
        print(f'Sandbox static schema check passed: {len(orders)} orders; accounts collection available. No submissions made.')


if __name__ == '__main__':
    check()
