# External integration boundary

External systems remain ordinary API clients. BUILTASUPPLY shares no databases, Django models, sessions, or code with them. Future clients use scoped, revocable, expirable hashed credentials; scopes such as `catalog:read` never imply order, wallet, audit, or admin access. RealEstate360+ is not implemented.
