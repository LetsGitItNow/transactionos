# Property Service Boundary

## Purpose

The property service turns an address supplied by a buyer into a canonical TransactionOS `PROPERTY` record. It is deliberately provider-neutral.

## Current development implementation

`POST /api/properties/resolve` currently:

1. normalizes whitespace in the address;
2. checks the local canonical store for an existing matching property;
3. creates a canonical property if none exists;
4. infers a coarse jurisdiction code where the country/region/city are known.

## Production adapter

Later, a real address/property provider can be inserted behind the same endpoint. The provider adapter should return a normalized object such as:

- canonical address
- city
- region
- postal code
- country
- latitude/longitude
- property type when available
- provider reference ID
- jurisdiction

The provider reference should be stored separately from the TransactionOS property ID so we are not coupled to a vendor's identifier.

## Important distinction

Address resolution is not the same thing as proof of ownership or authority to sell. Those are separate `PROPERTY_PARTY` / identity / authority workflows.
