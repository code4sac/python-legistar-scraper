import re
import json
import time
import collections
from datetime import datetime

from legistar.forms import Form
from legistar.tables import Table, TableRow
from legistar.views import SearchView, DetailView
from legistar.fields import FieldAggregator, make_item, gen_items
from legistar.fields import ElementAccessor
from legistar.base import DictSetDefault, NoClobberDict
from legistar.jurisdictions.utils import resolve_name, try_jxn_delegation
# https://github.com/guelo/legistar-scrape/compare/fgregg:master...master


class DateGetter:
    '''Parse a date using the datetime format string defined in
    the current jxn's config.
    '''
    def _get_date(self, label_text):
        fmt = self.get_config_value('datetime_format')
        text = self.get_field_text(label_text)
        if text is not None:
            dt = datetime.strptime(text, fmt)
            dt = self.cfg.datetime_add_tz(dt)
            return dt


class BillsFields(FieldAggregator, DateGetter):

    text_fields = (
        'file_number', 'law_number', 'type', 'status',
        'title', 'name', 'version', 'sponsor_office')

    @make_item('intro_date')
    def get_intro_data(self):
        return self._get_date('intro_date')

    @make_item('file_created')
    def get_file_created(self):
        return self._get_date('file_created')

    @make_item('sources', wrapwith=list)
    def gen_sources(self):
        grouped = collections.defaultdict(set)
        for note, url in self.chainmap['sources'].items():
            grouped[url].add(note)
        for url, notes in grouped.items():
            yield dict(url=url, note=', '.join(sorted(notes)))


class BillsSearchView(SearchView):
    sources_note = 'bills search'


class BillsSearchTableRow(TableRow, BillsFields):
    def get_detail_url(self):
        return self.get_field_url('file_number')


class BillsSearchTable(Table):
    sources_note = 'bills search table'


class BillsSearchForm(Form):
    '''Model the legistar "Legislation" search form.
    '''
    sources_note = 'bills search table'

    @try_jxn_delegation
    def get_query_simple(self, time_period=None, bodies=None, **kwargs):
        '''Get the query for the simple search page.
        '''
        configval = self.get_config_value
        time_period = time_period or configval('time_period')
        bodies = bodies or configval('types')
        query = {
            'ctl00_tabTop_ClientState': '{"selectedIndexes":["1"],"logEntries":[],"scrollState":{}}',
            'ctl00_RadScriptManager1_TSM': ';;System.Web.Extensions, Version=4.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35:en-US:fa6755fd-da1a-49d3-9eb4-1e473e780ecd:ea597d4b:b25378d2;Telerik.Web.UI, Version=2014.1.403.45, Culture=neutral, PublicKeyToken=121fae78165ba3d4:en-US:68d9452f-f268-45b2-8db7-8c3bbf305b8d:16e4e7cd:f7645509:24ee1bba:e330518b:88144a7a:1e771326:8e6f0d33:ed16cbdc:f46195d3:19620875:874f8ea2:cda80b3:383e4ce8:2003d0b8:aa288e2d:258f1c72:c128760b:c8618e41:1a73651d:333f8d94:58366029',
            configval('types_el_name'): bodies,
            configval('time_period_el_name'): time_period,
            configval('button_el_name'): configval('button'),
            configval('id_el_name'): configval('id'),
            configval('text_el_name'): configval('text'),
            }
        query.update(kwargs)
        self.debug('Query is %r' % query)
        query = dict(self.client.state, **query)
        return query

    @try_jxn_delegation
    def get_pagination_query(self, **kwargs):
        '''Get the query for the next page.
        '''
        configval = self.get_config_value
        query = self.get_query(**kwargs)
        query.pop('ctl00_ContentPlaceHolder1_lstMax_ClientState', None)
        query.pop('ctl00$ContentPlaceHolder1$btnSearch2', None)
        query = dict(self.client.state, **query)
        return query

    @try_jxn_delegation
    def get_query_advanced(self, time_period=None, bodies=None, **kwargs):
        '''Get the basic query for the advanced search page.
        '''
        configval = self.get_config_value
        time_period = time_period or configval('time_period')
        query = {
          'ctl00$ContentPlaceHolder1$btnSearch2': 'Search Legislation',
          'ctl00$ContentPlaceHolder1$lstMax': 'All',
          'ctl00$ContentPlaceHolder1$lstYearsAdvanced': time_period,
          }
        query.update(kwargs)
        self.debug('Query is %r' % query)
        query = dict(self.client.state, **query)
        return query

    def _writedoc(self):
        import lxml.html
        with open('current_legistar_doc.html', 'wb') as f:
            f.write(lxml.html.tostring(self.doc))

    @try_jxn_delegation
    def get_query(self, *args, **kwargs):
        if self.default_search_is_simple():
            self.switch_to_advanced_search()
        return self.get_query_advanced(**kwargs)

    def switch_to_advanced_search(self):
        self.debug('Switching to advanced search form.')
        query = dict(__EVENTTARGET='ctl00$ContentPlaceHolder1$btnSwitch')
        self.submit(query)

    def default_search_is_simple(self):
        '''Is the default page the simple search interface? Or advanced?
        As of now, seems only Chicago defaults to the advanced search page.
        This guesses by looking for a known advanced search param name.
        '''
        advanced_id = self.get_config_value('advanced_time_period_el_name')
        advanced = bool(self.doc.xpath('//*[@name="%s"]' % advanced_id))
        if advanced:
            self.debug('Found advanced search interface at %r' % self.url)
            return False
        else:
            self.debug('Found simple search interface at %r' % self.url)
            return True


class BillsDetailView(DetailView, BillsFields):
    sources_note = 'bill detail'
    text_fields = ('version', 'name')

    @make_item('agenda')
    def get_agenda_date(self):
        return self._get_date('agenda')

    @make_item('enactment_date')
    def get_enactment_date(self):
        return self._get_date('enactment_date')

    @make_item('final_action')
    def get_final_action(self):
        return self._get_date('final_action')

    @make_item('sponsors', wrapwith=list)
    def gen_sponsors(self):
        sponsors = self.get_field_text('sponsors')
        for name in re.split(r',\s+', sponsors):
            name = name.strip()
            if name:
                yield dict(name=name)

    @make_item('documents', wrapwith=list)
    def gen_documents(self):
        for el in self.xpath('attachments', './/a'):
            data = ElementAccessor(el)
            url = data.get_url()

            resp = self.client.head(url=url)
            media_type = resp.headers['content-type']

            yield dict(
                name=data.get_text(),
                links=[dict(
                    url=data.get_url(),
                    media_type=media_type)])

    @make_item('actions', wrapwith=list)
    def gen_action(self):
        yield from self.Form(self)


class BillsDetailTable(Table):
    sources_note = 'bill detail table'


class BillsDetailForm(Form):
    skip_first_submit = True
    sources_note = 'bill detail'


class BillsDetailTableRow(TableRow, FieldAggregator, DateGetter):
    sources_node = 'bill action table'
    disable_aggregator_funcs = True
    text_fields = (
        ('action_by', 'organization'),
        ('action', 'text'),
        'version',
        'result',
        'journal_page',
        )

    def get_detail_viewtype(self):
        return BillsDetailAction

    def get_detail_url(self):
        return self.get_media_url('action_details')

    @make_item('date')
    def get_date(self):
        return self._get_date('date')

    def _get_media(self, label):
        '''Given a field label, get it's url (if any) and send a head
        request to determine the content_type. Return a dict.
        '''
        data = self.get_field_data(label)
        url = data.get_url()
        if url is None:
            raise self.SkipItem()
        resp = self.client.head(url=url)
        media_type = resp.headers['content-type']
        return dict(
            name=data.get_text(),
            links=[dict(
                url=data.get_url(),
                media_type=media_type)])

    @make_item('media', wrapwith=list)
    def gen_media(self):
        for label in self.get_config_value('pupa_media'):
            try:
                yield self._get_media(label)
            except self.SkipItem:
                continue


class ActionBase(FieldAggregator):
    disable_aggregator_funcs = True

    def get_prefix(self):
        '''The settings prefix for this view.
        '''
        return 'BILL_ACTION'


class BillsDetailAction(DetailView, ActionBase):
    sources_note = 'bill action detail'

    text_fields = (
        'file_number', 'type', 'title', 'mover', 'seconder',
        'result', 'agenda_note', 'minutes_note', 'action',
        'action_text')

    @make_item('votes', wrapwith=list)
    def gen_votes(self):
        table_path = self.get_config_value('table_class')
        Table = resolve_name(table_path)
        yield from self.make_child(Table, self)

    @make_item('sources', wrapwith=list)
    def gen_sources(self):
        grouped = collections.defaultdict(set)
        for note, url in self.chainmap['sources'].items():
            grouped[url].add(note)
        for url, notes in grouped.items():
            yield dict(url=url, note=', '.join(sorted(notes)))


class BillsDetailActionTable(Table, ActionBase):
    sources_note = 'bill action detail table'

    def get_table_cell_type(self):
        path = self.get_config_value('tablecell_class')
        return resolve_name(path)

    def get_table_row_type(self):
        path = self.get_config_value('tablerow_class')
        return resolve_name(path)


class BillsDetailActionTableRow(TableRow, ActionBase):
    sources_node = 'bill action detail table'
    text_fields = ('person', 'vote')
