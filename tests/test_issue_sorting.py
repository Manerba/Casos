"""Sorting/filtering applies before pagination across the full issue collection."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from dashboard import database, issue_service as service
from dashboard.errors import ApplicationError


class IssueSortingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='casos-sorting-')
        self.addCleanup(tmp.cleanup)
        for key, value in {'DB_DIR': Path(tmp.name), 'DB_PATH': Path(tmp.name)/'casos.db'}.items():
            p = patch.object(database, key, value)
            p.start()
            self.addCleanup(p.stop)
        database.init_db()
        self.user = {'id': 1}
        self.items = [service.create_issue(data, self.user) for data in (
            {'title':'Zulu','priority':1}, {'title':'Bravo','priority':90,'deadline':'2026-10-21','assigned_to':1},
            {'title':'Alpha','priority':50,'deadline':'2026-10-20'},
        )]

    def test_global_order_null_deadline_and_unassigned_filter(self):
        first = service.list_issues(self.user, limit=1, sort_by='title', sort_direction='asc')
        second = service.list_issues(self.user, limit=1, offset=first['next_offset'], sort_by='title', sort_direction='asc')
        self.assertEqual([first['items'][0]['title'], second['items'][0]['title']], ['Alpha','Bravo'])
        self.assertEqual(service.list_issues(self.user, limit=1, sort_by='priority')['items'][0]['title'], 'Bravo')
        self.assertEqual([i['title'] for i in service.list_issues(self.user, sort_by='deadline')['items']], ['Bravo','Alpha','Zulu'])
        self.assertEqual({i['title'] for i in service.list_issues(self.user, unassigned=True)['items']}, {'Alpha','Zulu'})

    def test_order_identifiers_and_contradictory_filters_are_rejected(self):
        for kwargs in ({'sort_by':'id; DROP TABLE issues'}, {'sort_direction':'desc;--'},
                       {'sort_by':[]}, {'unassigned':True,'assigned_to':1}, {'unassigned':'yes'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ApplicationError):
                service.list_issues(self.user, **kwargs)
        self.assertEqual(service.list_issues(self.user)['total'], 3)


if __name__ == '__main__':
    unittest.main()
