import type {OrbitUser} from '../../lib/workspace';
import AccountAccess from './AccountAccess';
import CoinbaseConnection from './CoinbaseConnection';

export default function AccountPage({user}:{user:OrbitUser}) {
  return <div className="account-page"><AccountAccess user={user}/><CoinbaseConnection user={user}/></div>;
}
