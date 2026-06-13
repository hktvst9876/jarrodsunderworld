"""
integrations/shopify.py — Shopify Admin GraphQL client.

Operations:
  create_product()           — creates product + default variant with price
  update_variant_price()     — change selling price later
  list_publications()        — find sales channel IDs (TikTok Shop, Meta Shop, Online Store)
  publish_to_channels()      — publish a product to specified sales channels
  create_collection()        — group products into a "BBQ Essentials" collection
  delete_product()           — used when dumping a store

Token scopes required on the Shopify private app:
  write_products, read_products,
  write_publications, read_publications,
  write_inventory, read_inventory
"""

from __future__ import annotations
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.formulas import ProductEconomics, contribution_margin

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

STORE = os.environ.get("SHOPIFY_STORE_DOMAIN", "")
TOKEN = os.environ.get("SHOPIFY_ADMIN_TOKEN", "")
API_VERSION = "2024-10"


def _url() -> str:
    return f"https://{STORE}/admin/api/{API_VERSION}/graphql.json"


def _headers() -> dict:
    return {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}


def _check_creds() -> None:
    if not STORE or not TOKEN:
        raise RuntimeError("SHOPIFY_STORE_DOMAIN and SHOPIFY_ADMIN_TOKEN required in .env")


def _gql(query: str, variables: dict | None = None) -> dict:
    _check_creds()
    r = requests.post(
        _url(),
        json={"query": query, "variables": variables or {}},
        headers=_headers(),
        timeout=20,
    )
    r.raise_for_status()
    result = r.json()
    if "errors" in result:
        raise RuntimeError(f"Shopify GraphQL error: {result['errors']}")
    return result.get("data", {})


def _assert_cm_positive(price: float, cost: float,
                        fulfillment_shipping: float = 0.0) -> None:
    econ = ProductEconomics(
        selling_price=price, cogs=cost,
        fulfillment_shipping=fulfillment_shipping,
        payment_fee=price * 0.029 + 0.30,
        platform_fee=0,
    )
    cm = contribution_margin(econ)
    if cm <= 0:
        raise ValueError(
            f"Refusing to create product with non-positive CM: "
            f"price={price} cost={cost} fees={econ.payment_fee:.2f} CM={cm:.2f}"
        )


# ---------- Products ----------

CREATE_PRODUCT_MUTATION = """
mutation CreateProduct($input: ProductInput!) {
  productCreate(input: $input) {
    product {
      id
      title
      handle
      variants(first: 1) { edges { node { id sku price inventoryItem { id } } } }
    }
    userErrors { field message }
  }
}
"""

UPDATE_VARIANT_MUTATION = """
mutation UpdateVariant($input: ProductVariantInput!) {
  productVariantUpdate(input: $input) {
    productVariant { id price sku }
    userErrors { field message }
  }
}
"""


def create_product(name: str, price: float, cost: float,
                   description: str = "", sku: str | None = None,
                   image_urls: list[str] | None = None,
                   product_type: str = "BBQ Equipment",
                   vendor: str = "Smokehouse SG",
                   tags: list[str] | None = None,
                   dry_run: bool = False) -> dict:
    """
    Create a product with a default variant priced at `price`.

    Returns: {"product_id": "gid://...", "variant_id": "gid://...", "handle": "..."}
    Raises:  ValueError if CM <= 0, RuntimeError if API rejects.
    """
    _assert_cm_positive(price, cost)

    variant: dict = {"price": f"{price:.2f}", "inventoryPolicy": "CONTINUE"}
    if sku:
        variant["sku"] = sku

    product_input: dict = {
        "title": name,
        "descriptionHtml": description,
        "productType": product_type,
        "vendor": vendor,
        "status": "DRAFT",  # never auto-publish; human approval flips to ACTIVE
        "variants": [variant],
    }
    if tags:
        product_input["tags"] = tags
    if image_urls:
        product_input["images"] = [{"src": u} for u in image_urls]

    if dry_run:
        return {
            "product_id": "dry_run_product_gid",
            "variant_id": "dry_run_variant_gid",
            "handle": name.lower().replace(" ", "-"),
            "_dry_run": True,
            "_input": product_input,
        }

    data = _gql(CREATE_PRODUCT_MUTATION, {"input": product_input})
    payload = data.get("productCreate", {})
    errors = payload.get("userErrors", [])
    if errors:
        raise RuntimeError(f"productCreate userErrors: {errors}")
    product = payload.get("product")
    if not product:
        raise RuntimeError(f"productCreate returned no product: {payload}")

    variant_node = product["variants"]["edges"][0]["node"] if product["variants"]["edges"] else {}
    return {
        "product_id": product["id"],
        "variant_id": variant_node.get("id"),
        "handle": product["handle"],
    }


def update_variant_price(variant_id: str, new_price: float,
                          dry_run: bool = False) -> None:
    if dry_run:
        print(f"DRY RUN: would set variant {variant_id} price to {new_price:.2f}")
        return
    data = _gql(UPDATE_VARIANT_MUTATION, {
        "input": {"id": variant_id, "price": f"{new_price:.2f}"}
    })
    errors = data.get("productVariantUpdate", {}).get("userErrors", [])
    if errors:
        raise RuntimeError(f"productVariantUpdate userErrors: {errors}")


# ---------- Sales channels (publications) ----------

LIST_PUBLICATIONS_QUERY = """
query ListPublications {
  publications(first: 25) {
    edges { node { id name } }
  }
}
"""


def list_publications() -> list[dict]:
    """
    Return all sales channel publications on the store.

    Common names: "Online Store", "TikTok Shop", "Facebook & Instagram",
    "Google & YouTube", "Shop". Each must be installed first via Shopify Admin.
    """
    data = _gql(LIST_PUBLICATIONS_QUERY)
    return [{"id": e["node"]["id"], "name": e["node"]["name"]}
            for e in data["publications"]["edges"]]


PUBLISH_MUTATION = """
mutation Publish($id: ID!, $input: [PublicationInput!]!) {
  publishablePublish(id: $id, input: $input) {
    publishable { availablePublicationCount { count } }
    userErrors { field message }
  }
}
"""


def publish_to_channels(product_id: str, publication_ids: list[str],
                        dry_run: bool = False) -> None:
    """
    Publish a product to the given sales channels.

    Use list_publications() to discover IDs, then pass the ones you want.
    """
    if dry_run:
        print(f"DRY RUN: would publish {product_id} to {publication_ids}")
        return
    data = _gql(PUBLISH_MUTATION, {
        "id": product_id,
        "input": [{"publicationId": pid} for pid in publication_ids],
    })
    errors = data.get("publishablePublish", {}).get("userErrors", [])
    if errors:
        raise RuntimeError(f"publishablePublish userErrors: {errors}")


# ---------- Collections (for niche grouping) ----------

CREATE_COLLECTION_MUTATION = """
mutation CreateCollection($input: CollectionInput!) {
  collectionCreate(input: $input) {
    collection { id title handle }
    userErrors { field message }
  }
}
"""


def create_collection(title: str, description: str = "",
                      product_ids: list[str] | None = None,
                      dry_run: bool = False) -> dict:
    """Create a manual collection grouping products under a niche heading."""
    input_data: dict = {"title": title, "descriptionHtml": description}
    if product_ids:
        input_data["products"] = product_ids

    if dry_run:
        return {"collection_id": "dry_run_collection_gid", "_dry_run": True}

    data = _gql(CREATE_COLLECTION_MUTATION, {"input": input_data})
    payload = data.get("collectionCreate", {})
    errors = payload.get("userErrors", [])
    if errors:
        raise RuntimeError(f"collectionCreate userErrors: {errors}")
    col = payload.get("collection", {})
    return {"collection_id": col.get("id"), "handle": col.get("handle")}


# ---------- Product deletion (used when dumping a store) ----------

DELETE_PRODUCT_MUTATION = """
mutation DeleteProduct($input: ProductDeleteInput!) {
  productDelete(input: $input) {
    deletedProductId
    userErrors { field message }
  }
}
"""


def delete_product(product_id: str, dry_run: bool = False) -> None:
    if dry_run:
        print(f"DRY RUN: would delete product {product_id}")
        return
    data = _gql(DELETE_PRODUCT_MUTATION, {"input": {"id": product_id}})
    errors = data.get("productDelete", {}).get("userErrors", [])
    if errors:
        raise RuntimeError(f"productDelete userErrors: {errors}")


# ---------- Demo ----------

if __name__ == "__main__":
    print("Shopify integration — dry run demo")
    result = create_product(
        name="Cast Iron Restorer",
        price=45.0,
        cost=12.0,
        description="<p>Professional-grade cast iron cookware cleaner & restorer.</p>",
        sku="CIR-001",
        product_type="BBQ Equipment",
        vendor="Smokehouse SG",
        tags=["bbq", "cast-iron", "cleaning"],
        dry_run=True,
    )
    print(f"Would create: {result}")
    update_variant_price(result["variant_id"], 49.0, dry_run=True)
    publish_to_channels(result["product_id"],
                        ["gid://shopify/Publication/123"], dry_run=True)
