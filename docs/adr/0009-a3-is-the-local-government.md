# A3 is the general-purpose local government, from government boundaries

NENA-STA-006.3 fills A3 with the municipality an address is in, and each **Package** carries an A3Polygon
layer beside its A2Polygon (the county or census division itself). We take A3 from government boundaries
only (Census TIGER, Statistics Canada), never from OSM or Overture divisions (ODbL) and never from the
**Source agency**'s city field, which is often a postal community. The unit is the general-purpose local
government: in the 12 "strong MCD" states (CT, ME, MA, MI, MN, NH, NJ, NY, PA, RI, VT, WI) the town,
township or city (TIGER county subdivisions with an active government, plus the independent cities, whose
county subdivision is only a stand-in), elsewhere the incorporated place,
and in Canada the census subdivision. An address in none of them is "Unincorporated". The trade-off:
villages and boroughs inside a strong-MCD town don't appear as A3, Census designated places (statistical)
never do, and TIGER lags annexations by up to a year, so an agency's own municipal boundary layer, once it
opts in and sends one, replaces ours (ADR 0001, 0005). Each Package's manifest reports how often a Record's
own community name agrees with the A3 we assigned, which shows where the two disagree.
