"""Configured sources discover recipes from bounded XML, gzip and HTML catalogs."""
from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

import collect_recipes as collector
from recipe_sources import load_sources, sources_from_data

HOST = "https://www.recipes.example.org"
RECIPE = HOST + "/recipe/123"


def xml(kind, *locations):
    entry = "sitemap" if kind == "sitemapindex" else "url"
    return (f'<{kind} xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' +
            "".join(f"<{entry}><loc>{location}</loc></{entry}>" for location in locations) +
            f"</{kind}>").encode()


class FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def fetch(self, url, limit, accept="text/html"):
        self.calls.append(url)
        if url not in self.responses:
            raise collector.CollectionError("Fixture page not found")
        value = self.responses[url]
        if isinstance(value, tuple):
            return value
        return value, "application/xml", url


class ConfiguredDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        path = Path(self.directory.name) / "sources.json"
        path.write_text(json.dumps({"example": {
            "canonical_host": "www.recipes.example.org",
            "hosts": ["www.recipes.example.org", "recipes.example.org"],
            "catalog_url": HOST + "/sitemap.xml",
            "recipe_pattern": r"/recipe/\d+",
            "catalog_pattern": r"/(?:sitemap\.xml|catalog(?:/\d+)?|maps/recipes-\d+\.xml(?:\.gz)?)",
            "aliases": ["example-old"],
        }}), encoding="utf-8")
        self.sources = load_sources(path)
        self.start = HOST + "/sitemap.xml"

    def discover(self, client, site="example"):
        return list(collector.discover(site, client, self.sources))

    def test_xml_index_and_gzip_urlset_use_configuration_only(self):
        child = HOST + "/maps/recipes-1.xml.gz"
        ignored = HOST + "/maps/authors-1.xml"
        client = FakeClient({
            self.start: xml("sitemapindex", child, ignored),
            child: gzip.compress(xml("urlset", RECIPE, "https://outside.example.org/recipe/99")),
        })
        self.assertEqual(self.discover(client), [RECIPE])
        self.assertEqual(client.calls, [self.start, child])

    def test_html_at_xml_url_is_detected_and_relative_links_normalized(self):
        page = b'''<!DOCTYPE html><html><body>
            <a href="/recipe/123?tracking=1#photo">Recipe</a>
            <a href="//recipes.example.org/recipe/123">Same recipe</a>
            <a href="https://outside.example.org/recipe/99">External</a>
            <a href="javascript:alert(1)">Script</a>
            <img src="/recipe/999">
            </body></html>'''
        client = FakeClient({self.start: (page, "text/html", self.start)})
        self.assertEqual(self.discover(client), [RECIPE])
        self.assertEqual(client.calls, [self.start])

    def test_html_catalog_pagination_is_followed_without_unrelated_pages(self):
        second = HOST + "/catalog/2"
        first_page = b'<html><a href="/catalog/2">Next</a><a href="/profile/12">Profile</a></html>'
        second_page = b'<html><a href="/recipe/123">Recipe</a><a href="/sitemap.xml">Cycle</a></html>'
        client = FakeClient({
            self.start: (first_page, "text/html", self.start),
            second: (second_page, "text/html", second),
        })
        self.assertEqual(self.discover(client), [RECIPE])
        self.assertEqual(client.calls, [self.start, second])

    def test_html_query_pagination_is_preserved_but_recipe_queries_are_removed(self):
        second = HOST + "/catalog?page=2"
        client = FakeClient({
            self.start: (b'<html><a href="/catalog?page=2">Next</a></html>', "text/html", self.start),
            second: (b'<html><a href="/recipe/123?tracking=1">Recipe</a></html>', "text/html", second),
        })
        self.assertEqual(self.discover(client), [RECIPE])
        self.assertEqual(client.calls, [self.start, second])

    def test_aliases_share_discovery_and_external_redirects_are_rejected(self):
        client = FakeClient({self.start: xml("urlset", RECIPE)})
        self.assertEqual(self.discover(client, "example-old"), [RECIPE])
        redirected = FakeClient({self.start: (xml("urlset", RECIPE), "application/xml", "https://outside.example.org/sitemap.xml")})
        with self.assertRaises(collector.CollectionError):
            self.discover(redirected)

    def test_broken_xml_is_not_treated_as_an_html_catalog(self):
        client = FakeClient({self.start: (b'<urlset><url><loc>broken', "application/xml", self.start)})
        with self.assertRaises(collector.CollectionError):
            self.discover(client)

    def test_discovery_budget_bounds_catalog_requests(self):
        responses = {self.start: (b'<html><a href="/catalog/1">Next</a></html>', "text/html", self.start)}
        for number in range(1, 20):
            url = HOST + f"/catalog/{number}"
            page = f'<html><a href="/recipe/{number}">Recipe</a><a href="/catalog/{number+1}">Next</a></html>'.encode()
            responses[url] = page, "text/html", url
        client = FakeClient(responses)
        progress = []
        list(collector.discover("example", client, self.sources, max_catalog_pages=10, progress_callback=progress.append))
        self.assertLessEqual(len(client.calls), 10)
        self.assertFalse(progress[-1]["complete"])
        self.assertEqual(progress[-1]["stop_reason"], "catalog_page_limit")

    def test_default_discovery_follows_more_than_ten_catalog_pages_until_exhausted(self):
        responses = {self.start: (b'<html><a href="/catalog/1">Next</a></html>', "text/html", self.start)}
        for number in range(1, 24):
            url = HOST + f"/catalog/{number}"
            next_link = f'<a href="/catalog/{number+1}">Next</a>' if number < 23 else ""
            responses[url] = f'<html><a href="/recipe/{number}">Recipe</a>{next_link}</html>'.encode(), "text/html", url
        progress = []
        found = list(collector.discover("example", FakeClient(responses), self.sources, progress_callback=progress.append))
        self.assertEqual(len(found), 23)
        self.assertTrue(progress[-1]["complete"])
        self.assertEqual(progress[-1]["catalog_pages"], 24)

    def test_homepage_widget_learns_full_catalog_and_categories_even_with_old_root_only_settings(self):
        settings = sources_from_data({"example": {
            "canonical_host": "www.recipes.example.org", "hosts": ["www.recipes.example.org"],
            "catalog_url": HOST + "/", "recipe_pattern": r"/retsepty/\d+-[^/]+", "catalog_pattern": "/",
        }})
        pages = {HOST + "/": (b'<html><a href="/retsepty">All recipes</a><a href="/retsepty/tags/soup">Soups</a>' +
                                        b''.join(f'<a href="/retsepty/{i}-old">Old</a>'.encode() for i in range(8)) + b'</html>', "text/html", HOST + "/"),
                 HOST + "/retsepty": (b'<html><a href="/retsepty/9-new">New</a><a href="/retsepty?page=2">Next</a></html>', "text/html", HOST + "/retsepty"),
                 HOST + "/retsepty?page=2": (b'<html><a href="/retsepty/10-new">Newer</a></html>', "text/html", HOST + "/retsepty?page=2"),
                 HOST + "/retsepty/tags/soup": (b'<html><a href="/retsepty/11-soup">Soup</a></html>', "text/html", HOST + "/retsepty/tags/soup")}
        categories, recipes, progress = [], [], []
        found = list(collector.discover("example", FakeClient(pages), settings, on_category=categories.append,
                                       on_recipe=recipes.append, progress_callback=progress.append))
        self.assertEqual(len(found), 11)
        self.assertIn({"url": HOST + "/retsepty/tags/soup", "title": "Soups", "parent_url": HOST + "/"}, categories)
        self.assertEqual(next(item["category_url"] for item in recipes if item["url"].endswith("10-new")), HOST + "/retsepty")
        self.assertTrue(progress[-1]["complete"])

    def test_category_scan_stays_selected_and_does_not_seed_global_maps(self):
        start = HOST + "/catalog/soup"
        settings = sources_from_data({"example": {
            "canonical_host": "www.recipes.example.org", "hosts": ["www.recipes.example.org"],
            "catalog_url": start, "recipe_pattern": r"/recipe/\d+", "catalog_pattern": r"/catalog(?:/[^/]+)?",
        }})
        pages = {start: (b'<html><a href="/catalog/meat">Meat</a><a href="/recipe/1">Soup</a><a href="?page=2">Next</a></html>', "text/html", start),
                 start + "?page=2": (b'<html><a href="/recipe/2">Another soup</a></html>', "text/html", start + "?page=2")}
        client = FakeClient(pages)
        found = list(collector.discover("example", client, settings, category_scope=True))
        self.assertEqual(found, [HOST + "/recipe/1", HOST + "/recipe/2"])
        self.assertEqual(client.calls, [start, start + "?page=2"])

    def test_root_site_follows_a_robots_advertised_sitemap_outside_old_catalog_pattern(self):
        settings = sources_from_data({"example": {
            "canonical_host": "www.recipes.example.org", "hosts": ["www.recipes.example.org"],
            "catalog_url": HOST + "/", "recipe_pattern": r"/recipe/\d+", "catalog_pattern": "/",
        }})
        pages = {HOST + "/": (b'<html>Home</html>', "text/html", HOST + "/"),
                 HOST + "/robots.txt": (f'User-agent: *\nSitemap: {HOST}/maps/index.xml'.encode(), "text/plain", HOST + "/robots.txt"),
                 HOST + "/maps/index.xml": xml("sitemapindex", HOST + "/maps/recipes.xml"),
                 HOST + "/maps/recipes.xml": xml("urlset", RECIPE)}
        self.assertEqual(list(collector.discover("example", FakeClient(pages), settings)), [RECIPE])

    def test_selected_category_follows_path_pagination_with_an_exact_catalog_pattern(self):
        start = HOST + "/catalog/soup"
        second = start + "/page/2"
        settings = sources_from_data({"example": {
            "canonical_host": "www.recipes.example.org", "hosts": ["www.recipes.example.org"],
            "catalog_url": start, "recipe_pattern": r"/recipe/\d+", "catalog_pattern": "/catalog/soup",
        }})
        pages = {start: (f'<html><a href="{second}">Next</a><a href="/catalog/meat">Meat</a><a href="/sitemap.xml">Map</a><a href="/recipe/1">Soup</a></html>'.encode(), "text/html", start),
                 second: (b'<html><a href="/recipe/2">Another soup</a></html>', "text/html", second)}
        client = FakeClient(pages)
        recipes, categories = [], []
        found = list(collector.discover("example", client, settings, category_scope=True,
                                       on_recipe=recipes.append, on_category=categories.append))
        self.assertEqual(found, [HOST + "/recipe/1", HOST + "/recipe/2"])
        self.assertEqual(client.calls, [start, second])
        self.assertEqual({item["category_url"] for item in recipes}, {start})
        self.assertEqual(len(categories), 1)


if __name__ == "__main__":
    unittest.main()
