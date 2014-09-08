# -*- encoding: utf-8 -*-
##############################################################################
#
#   Copyright (C) 2014 Akretion David BEAL
#                               Sébastien BEAU
#
#   This program is free software: you can redistribute it and/or modify
#   it under the terms of the GNU Affero General Public License as
#   published by the Free Software Foundation, either version 3 of the
#   License, or (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU Affero General Public License for more details.
#
#   You should have received a copy of the GNU Affero General Public License
#   along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from openerp.osv import orm, fields
from openerp.tools.config import config

from laposte_api.colissimo_and_so import (
    ColiPoste,
    InvalidDataForMako,
    InvalidWebServiceRequest)

from laposte_api.exception_helper import (
    InvalidWeight,
    InvalidSize,
    InvalidMissingField,
    InvalidCode,
    InvalidZipCode,
    InvalidCountry,
    InvalidSequence,
    InvalidKeyInTemplate,
    InvalidType)

from datetime import date

EXCEPT_TITLE = "'Colissimo and So' library Exception"


def raise_exception(orm, message):
    raise orm.except_orm(EXCEPT_TITLE, map_except_message(message))


def map_except_message(message):
    """Allows to map vocabulary from external library
    to Odoo vocabulary in Exception message
    """
    webservice_mapping = {
        'line2': 'line2 (rue du partner du bon de livraison)',
        '\\xe8': 'e',
        '\\xe9': 'e',
        '\\xe0': 'a',
    }
    model_mapping = {
        'sender': 'company and \ncarrier configuration',
        'delivery': 'delivery order',
        'address': 'customer/partner'}
    for key, val in model_mapping.items():
        message = message.replace('(model: ' + key, '\n(check model: ' + val)
    for key, val in webservice_mapping.items():
        message = message.replace(key, val)
    return message


def move_label_content(content, tag, value, axis='y'):
    """ move label content
        :param content: unicode: whole text to parse
        :param tag: str: string to search in content for replacement pupose
        :param value: integer: define position x or y in the label
        :param axis: char: direction x or y
    """
    cpn = tag.split(',')
    if axis == 'y':
        position = str(int(cpn[1]) + value)
        new_tag = '%s,%s' % (cpn[0], position)
    else:
        extract_pos = int(cpn[0][3:])
        position = extract_pos + value
        new_tag = '%s%s,%s' % (cpn[0][:3], position, cpn[1])
    return content.replace(tag, new_tag)


def modify_label_content(content):
    """ International web service label is too long
        to be printed correctly
    """
    tags = ['^FO270,920', '^FO30,920', '^FO670,920', '^FO290,970',
            '^FO27,995', '^FO170,1194', '^FO27,988']
    for tag in tags:
        content = move_label_content(content, tag, -30)
    return content


class AbstractColipostePicking(orm.AbstractModel):
    _name = 'abstract.coliposte.picking'
    _description = "Abstract Coliposte"

    def send_douane_doc(self, cr, uid, ids, field_n, arg, context=None):
        result = {}
        for elm in self.browse(cr, uid, ids):
            res = False
            if elm.state == 'done' and elm.carrier_type == 'colissimo':
                eu_country = False
                if elm.partner_id.country_id \
                        and elm.partner_id.country_id.intrastat:
                    # intrastat field identify european countries
                    eu_country = True
                if elm.carrier_code in ['8Q', '7Q']:
                    res = True
                if elm.carrier_code in ['EI', 'AI', 'SO'] and not eu_country:
                    res = True
                elif elm.carrier_code in ['9V', '9L'] \
                        and elm.partner_id.country_id \
                        and elm.partner_id.country_id.code == 'AD':
                    res = True
            result[elm.id] = res
        return result

    _columns = {
        'colipostefr_prise_en_charge': fields.char(
            '||| || |||| pch',
            size=64,
            help="""Code barre de prise en charge :
            cf documentation coliposte pour plus de détails
    - code étiquette sur 2 alfa.
    - coliss_order : valeur 1 ou 2 (selon la méthode de livraison)
    - code postal (5 alfa) ou   prefix pays (étranger)
      + 3 premiers caractères CP
    - N° du compte client fourni par le partner 'La Poste'
    - poids du colis sur 4 numeriques
    - 00 : assurance+recommandation (non implémenté à ce jour)
    - option 'non mécanisable' : valeur 1 ou 0
    - combinaison d'options : FTD+AR+CRBT (valeur de 0 à 7)
    - clé de liaison du code barre précédent sur 1 numérique
      (issu de l'avant dernier caractère)
    - clé de contrôle du code barre actuel sur 1 numérique
    """),
        'colipostefr_insur_recomm': fields.selection([
            ('01', '150 €'), ('02', '300 €'), ('03', '450 €'),
            ('04', '600 €'), ('05', '750 €'), ('06', '900 €'), ('07', '1050 €'),
            ('08', '1200 €'), ('09', '1350 €'), ('10', '1500 €'),
            #('21', 'R1'), ('22', 'R2'), ('23', 'R3'),  # TODO Recommandation level
            ],
            'Insurance',
            help="Insurance amount in € (add valorem)"),
        'colipostefr_send_douane_doc': fields.function(
            send_douane_doc,
            string='Send douane document',
            type='boolean',
            store=False,
            help="Define if document CN23 et CN11 should be printed/sent with the parcel"),
    }


class StockPicking(orm.Model):
    _inherit = ['stock.picking', 'abstract.coliposte.picking']
    _name = 'stock.picking'

    def _prepare_address_postefr(self, cr, uid, pick, context=None):
        address = {}
        for elm in ['name', 'city', 'zip']:
            address[elm] = pick.partner_id[elm]
        # 3 is the number of fields street
        # 35 is the field street max length
        res = self.pool['res.partner']._get_split_address(
            cr, uid, pick.partner_id, 3, 35, context=context)
        address['street'], address['street2'], address['street3'] = res
        if pick.partner_id.country_id.code and pick.partner_id.country_id.code:
            address['countryCode'] = pick.partner_id.country_id.code
        return address

    def _prepare_delivery_postefr(self, cr, uid, pick, context=None):
        today = date.today().strftime('%d/%m/%Y')
        params = {
            'ref_client': pick.name,
            'weight': pick.weight,
            'date': today,
        }
        if pick.carrier_code not in ['EI', 'AI', 'SO']:
            params.update({
                'cab_prise_en_charge': pick.colipostefr_prise_en_charge,
                'cab_suivi': pick.carrier_tracking_ref,
            })
        return params

    def _prepare_option_postefr(self, cr, uid, pick, context=None):
        option = {}
        if pick.option_ids:
            for opt in pick.option_ids:
                opt_key = str(opt.tmpl_option_id['code'].lower())
                option[opt_key] = True
        if pick.colipostefr_insur_recomm:
            #TODO improve this mechanism option
            option['insurance'] = pick.colipostefr_insur_recomm
        return option

    def _prepare_sender_postefr(self, cr, uid, pick, context=None):
        partner = self.pool['stock.picking.out']._get_label_sender_address(
            cr, uid, pick, context=context)
        sender = {'support_city': pick.company_id.colipostefr_support_city,
                  'password': pick.company_id.colipostefr_password}
        if partner.country_id:
            sender['country'] = partner.country_id.name
        fields = ['name', 'street', 'zip', 'city',
                  'phone', 'mobile', 'email']
        for elm in fields:
            sender[elm] = partner[elm]
        if pick.carrier_code == '6J':
            sender['chargeur'] = pick.company_id.colipostefr_account_chargeur
        return sender

    def _generate_coliposte_label(self, cr, uid, ids, pick, context=None):
        if pick.carrier_code:
            france = True
            if pick.carrier_code in ['EI', 'AI', 'SO']:
                france = False
            carrier = {}
            try:
                account = pick.company_id.colipostefr_account
                service = ColiPoste(account).get_service(
                    pick.carrier_type, pick.carrier_code)
            except (InvalidSize, InvalidCode, InvalidType) as e:
                raise_exception(orm, e.message)
            except Exception as e:
                raise orm.except_orm(
                    "'Colissimo and So' Library Error",
                    map_except_message(e.message))
            label_name = pick.carrier_code
            option = self._prepare_option_postefr(cr, uid, pick, context=context)
            if not france:
                if not pick.partner_id.country_id \
                        and not pick.partner_id.country_id.code:
                    raise orm.except_orm(
                        "'Colissimo and So' Library Error",
                        "EI/AI/BE carrier code must have a defined country code")
            else:
                sequence = self._get_sequence(
                    cr, uid, label_name, context=context)
                carrier['carrier_tracking_ref'] = service.get_cab_suivi(sequence)
                carrier['colipostefr_prise_en_charge'] = \
                    self._barcode_prise_en_charge_generate(
                        cr, uid, service, pick,
                        carrier['carrier_tracking_ref'],
                        option, context=context)
                self.write(cr, uid, [pick.id], carrier)
                pick = self.browse(cr, uid, pick.id, carrier)
            sender = self._prepare_sender_postefr(cr, uid, pick, context=context)
            delivery = self._prepare_delivery_postefr(cr, uid, pick, context=context)
            address = self._prepare_address_postefr(cr, uid, pick, context=context)
            label = {
                'file_type': 'zpl2',
                'name': pick.name + '.zpl',
            }
            try:
                # uncomment the line below to record a new test unit
                # based on picking datas
                if pick.company_id.colipostefr_unittest_helper and france:
                    test_id = self._get_xmlid(cr, uid, pick.id) or 'tmp'
                    service._set_unit_test_file_name(
                        test_id, sequence, carrier['carrier_tracking_ref'],
                        carrier['colipostefr_prise_en_charge'])
                result = service.get_label(
                    sender, delivery, address, option)
                if pick.carrier_code in ['EI', 'AI', 'SO']:
                    label['file'] = modify_label_content(result[0])
                    carrier['carrier_tracking_ref'] = result[2]
                    carrier['colipostefr_prise_en_charge'] = result[3]
                    self.write(cr, uid, [pick.id], carrier)
                    pick = self.browse(cr, uid, ids, context=context)[0]
                    if result[1]:
                        self._create_comment(cr, uid, pick, result[1], context=None)
                else:
                    label['file'] = result
                    if config.options.get('debug_mode', True):
                        # get file datas in clipboard for paste in zebra viewer
                        service._copy2clipboard(label['file'])
            except (InvalidDataForMako,
                    InvalidKeyInTemplate,
                    InvalidWebServiceRequest,
                    InvalidKeyInTemplate,
                    InvalidCountry,
                    InvalidMissingField) as e:
                raise_exception(orm, e.message)
            except Exception as e:
                if config.options.get('debug_mode', False):
                    raise
                else:
                    raise orm.except_orm(
                        "'Colissimo and So' Library Error", e.message)
        return [label]

    def generate_shipping_labels(self, cr, uid, ids, tracking_ids=None,
                                 context=None):
        if isinstance(ids, (long, int)):
            ids = [ids]
        assert len(ids) == 1
        picking = self.browse(cr, uid, ids[0], context=context)
        if picking.carrier_type in ['colissimo', 'so_colissimo']:
            return self._generate_coliposte_label(cr, uid, ids, picking, context=context)
        return super(StockPicking, self).generate_shipping_labels(
            cr, uid, ids, tracking_ids=tracking_ids, context=context)

    def _filter_message(self, cr, uid, mess_type, context=None):
        """ Allow to exclude returned message according their type.
            Only used by
        """
        if mess_type in ['INFOS']:
            return False
        return True

    def _create_comment(self, cr, uid, pick, messages, context=None):
        if pick.company_id.colipostefr_webservice_message:
            mess_title = "Web Service ColiPoste International<ul>%s</ul>"
            message = ''
            for mess in messages:
                if 'type' in mess:
                    if self._filter_message(cr, uid, mess['type'], context=context):
                        message += '<li>%s %s: %s</li>\n' \
                                   % (mess['type'], mess['id'], mess['libelle'])
                elif isinstance(mess, (str, unicode)):
                    message += unicode(mess)
            if len(message) > 0:
                vals = {
                    'res_id': pick.id,
                    'model': 'stock.picking',
                    'body': mess_title % message,
                    'type': 'comment',
                }
                self.pool['mail.message'].create(cr, uid, vals, context=context)
        return True

    def _get_xmlid(self, cr, uid, id):
        "only used in development"
        xml_id_dict = self.get_xml_id(cr, uid, [id])
        xml_id = False
        if xml_id_dict:
            xml_id = xml_id_dict[id]
            xml_id = xml_id[xml_id.find('.')+1:]
        return xml_id.replace('stock_picking_', '')

    def _get_sequence(self, cr, uid, label, context=None):
        #TODO : foreigner service sender:
        #sequence will be provided by webservice since 2014 July
        return self.pool['ir.sequence'].next_by_code(
            cr, uid, 'stock.picking_' + label, context=context)

    def _barcode_prise_en_charge_generate(
            self, cr, uid, service, picking, carrier_track, option, context=None):
        """
        :return: the second barcode
        """
        if picking.carrier_code:
            infos = {
                'zip': picking.partner_id.zip or '',
                'countryCode': picking.partner_id
                and picking.partner_id.country_id
                and picking.partner_id.country_id.code or '',
                'weight': picking.weight,
                'carrier_track': carrier_track,
            }
            infos.update(option)
            try:
                barcode = service.get_cab_prise_en_charge(infos)
            except (InvalidWeight, Exception) as e:
                raise_exception(orm, e.message)
        return barcode


class StockPickingOut(orm.Model):
    """
    TODO : manage coliss_assur with colissimo carrier_code :
        => hide/display and use or not this selection
            - Assurance : EI, AI, 7Q, 8V, 9V
            - Recommandation: 8V, 9V, 7Q
    """
    _inherit = ['stock.picking.out', 'abstract.coliposte.picking']
    _name = 'stock.picking.out'

    def copy(self, cr, uid, id, default=None, context=None):
        if default is None:
            default = {}
        default.update({
            'deposit_slip_id': None,
            #'name': None,
            'carrier_tracking_ref': None,
            'colipostefr_prise_en_charge': None,
        })
        return super(StockPickingOut, self).copy(
            cr, uid, id, default, context=context)

    def get_shipping_cost(self, cr, uid, ids, context=None):
        return 0


class StockPickingIn(orm.Model):
    _inherit = 'stock.picking.in'

    def action_generate_carrier_label(self, cr, uid, ids, context=None):
        raise orm.except_orm(
            "Return label",
            "Return Label is not implemented for "
            "'Colissimo/So Colissimo' Coliposte \n"
            "Ask us for service proposal, http://www.akretion.com/contact")


class ShippingLabel(orm.Model):
    _inherit = 'shipping.label'

    def _get_file_type_selection(self, cr, uid, context=None):
        selection = super(ShippingLabel, self)._get_file_type_selection(
            cr, uid, context=None)
        selection.append(('zpl2', 'ZPL2'))
        return selection
