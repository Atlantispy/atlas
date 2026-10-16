import sys
print(sys.version)
import rf_common as c
print(c.G.version(), c.A.exact_library())
print(hash(c.G.mpq(1,2)) == hash(c.F(1,2)), hash(c.G.mpq(0)), hash(c.G.mpq(1)))
