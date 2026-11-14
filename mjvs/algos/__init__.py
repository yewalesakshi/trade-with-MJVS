"""The 8 MJVS algos, in the order shown on the website."""
from .scalping import Scalping
from .intraday import Intraday
from .short_term import ShortTerm
from .swing import Swing
from .long_term import LongTerm
from .penny import Penny
from .futures import NiftyFutureSwing
from .options import Options

ALGOS = {a.id: a for a in (Scalping(), Intraday(), ShortTerm(), Swing(), LongTerm(), Penny(), NiftyFutureSwing(), Options())}
