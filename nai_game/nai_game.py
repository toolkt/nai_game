# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from datetime import datetime, timedelta
from odoo.exceptions import ValidationError, AccessError, UserError
from odoo.tools.mimetypes import guess_mimetype

import pytz
import base64
from tempfile import TemporaryFile
import tempfile

import re
import pprint
import base64
import pandas as pd
import numpy as np
import xlrd
from xlrd import open_workbook
import mmap
import io
import csv


from sklearn.feature_extraction.text import CountVectorizer
from sklearn.metrics.pairwise import cosine_similarity


FILE_TYPE_DICT = {
    'text/csv': ('csv','SAP'),
    'application/octet-stream': ('csv','SAP'),
    'application/vnd.ms-excel': ('xl','AS400'),
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ('xlsx','xlsx'),
    'application/vnd.ms-excel': ('xls','xls'),
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ('xl','AS400'),
}


def read_xls_to_dict(excel_file_field,sheet_name):
        book    = open_workbook(file_contents=base64.b64decode(excel_file_field))
        sheet   = book.sheet_by_name(sheet_name)
        headers = dict( (i, sheet.cell_value(0, i) ) for i in range(sheet.ncols) ) 

        return ( dict( (headers[j], sheet.cell_value(i, j)) for j in headers ) for i in range(1, sheet.nrows) )


class NaiGame(models.Model):
    _name = 'nai.game'
    _inherit = ['mail.thread']


    @api.onchange('results')
    def onchange_upload_file(self):
        if self.results:
            self.write({'results_data': [(5, 0, 0)]})
            self.write({'answers_data': [(5, 0, 0)]})

            (file_extension,source) = FILE_TYPE_DICT.get(guess_mimetype(base64.b64decode(self.results)), (None,None))
            #check if Excel File
            if file_extension == 'xl':
                data1 = read_xls_to_dict(self.results,'FILE 1')

                result = []
                for d in data1:
                    # dt = datetime.fromordinal(datetime(1900, 1, 1).toordinal() + d['Timestamp'] - 2)
                    # tt = dt.timetuple()

                    vals = {'recipient':d['Recipients'],
                        'sender':d['Sender'],
                        'timestamp':datetime(*xlrd.xldate_as_tuple(d['Timestamp'], 0))}

                    result.append((0,0,vals))
                    # print (d,vals)

                self.results_data = result


                answers = []
                ans = read_xls_to_dict(self.results,'ANSWERS')
                for d in ans:
                    vals = {
                        'game_id':self.id,
                        'sender':d['Sender'],
                        'answer':d['Answer'],
                        'corona': False,
                        }

                    if d['Corona']:
                        vals['corona'] = True

                    answers.append((0,0,vals))

                self.answers_data = answers



    def compute_totals(self):
        for rec in self:

            data2 = read_xls_to_dict(self.results,'FILE 2')
            for d in data2:

                ans = rec.env['nai.game.answer'].search([('game_id','=',rec.id),('sender','=',d['Recipients'])],limit=1)[0]
                a1 = ans.answer
                a2 = d['Answer']

                corpus = [a1, a2]
                vectorizer = CountVectorizer(ngram_range=(1, 3))
                vectorizer.fit(corpus)

                x1 = vectorizer.transform([a1])
                x2 = vectorizer.transform([a2])

                sim = cosine_similarity(x1, x2)

                min_correctness = 1
                if rec.correctness_threshold > 0: 
                    min_correctness = rec.correctness_threshold

                i = rec.env['nai.game.results'].search([('game_id','=',rec.id),('recipient','=',d['Sender']),('sender','=',d['Recipients'])],limit=1)

                timestamp1 = i.timestamp
                timestamp2 = datetime(*xlrd.xldate_as_tuple(d['Timestamp'], 0))



                vals = {
                    'timestamp2':timestamp2, 
                    'answer':d['Answer'],
                    'answer_similarity':sim[0],
                    'correct': False,
                    'answered': False,
                    'corona': False,
                }

                if sim[0] >= min_correctness :
                    vals['correct'] = True

                if d['Answer']:
                    vals['answered'] = True

                if ans.corona:
                    vals['corona'] = True

                if not (not timestamp2 or not timestamp1):
                    print (timestamp2,timestamp1)
                    duration_delta = timestamp2-timestamp1 #datetime.strptime(timestamp2, '%Y-%m-%d %H:%M:%S') - datetime.strptime(timestamp1, '%Y-%m-%d %H:%M:%S') 
                    duration_in_s = duration_delta.total_seconds() 
                    duration = divmod(duration_in_s, 60)[0] 
                    vals['duration'] = duration

                # print (vals)
                i.write(vals)


    def download_results(self):
        for rec in self:
            output = io.StringIO()
            writer = csv.writer(output, delimiter=',', quoting=csv.QUOTE_ALL)

            hdr = []
            writer.writerow(['Employee','Sender','Duration','Answer','Similarity','Correct','Answered','Corona'])
            for r in rec.results_data:
                writer.writerow([r['sender'],r['recipient'],r['duration'],r['answer'],r['answer_similarity'],r['correct'],r['answered'],r['corona']])

            xy = output.getvalue().encode('utf-8')
            file = base64.encodestring(xy)


            import xlsxwriter
            workbook = xlsxwriter.Workbook('myfile.xlsx')
            worksheet = workbook.add_worksheet()


            rec.write({'csv_file':file})

            button = {
                'type' : 'ir.actions.act_url',
                'url': '/web/content/nai.game/%s/csv_file/results.csv?download=true'%(rec.id),
                'target': 'new'
                }
            return button


    def compute_score(self):
        for rec in self:
            print("Cmpute Score")

            self.write({'scores_data': [(5, 0, 0)]})

            query = """
                SELECT 
                %s as game_id,
                recipient as sender,
                AVG(duration) avg_time,
                SUM(CASE WHEN answered THEN 1 ELSE 0 END) total_answered,
                SUM(CASE WHEN corona THEN 1  ELSE 0 END) total_corona,
                SUM(CASE WHEN correct THEN 1  ELSE 0 END) total_correct
                FROM 

                (SELECT
                recipient, 
                sender, 
                MAX(duration) duration,
                bool_or(answered) answered,
                bool_or(corona) corona,
                bool_or(correct) correct,
                MAX(game_id) game_id
                from nai_game_results ngr
                where recipient != '' and game_id = %s
                group by recipient,sender
                )
                AS score
                group by recipient
                order by total_correct desc,  recipient

            """ % (rec.id,rec.id)

            self._cr.execute(query)
            result = self._cr.dictfetchall()

            new_records = []
            for r in result:
                new_records.append((0,0,r))

            rec.scores_data = new_records



    name = fields.Char('Name')
    description = fields.Char('Description')
    ws_labels = fields.Char("Worksheet Labels", help="Comma Separated ie File 1,File 2")
    file_text = fields.Text("Paste Here")
    results = fields.Binary("Results")
    date = fields.Date("Date", default=fields.Datetime.now())
    correctness_threshold = fields.Float("Correctness Threshold")

    results_data = fields.One2many('nai.game.results','game_id','Results')
    answers_data = fields.One2many('nai.game.answer','game_id','Answers')
    scores_data = fields.One2many('nai.game.score','game_id','Scores')

    csv_file = fields.Binary('CSV File')

class NaiGameResults(models.Model):
    _name = 'nai.game.results'

    game_id = fields.Many2one('nai.game')
    recipient = fields.Char('Employee')
    sender = fields.Char('Sender')
    timestamp = fields.Datetime('Timestamp')
    timestamp2 = fields.Datetime('Timestamp')
    duration = fields.Float('Duration')
    answer = fields.Char("Answer")
    answer_similarity = fields.Float("Similarity")
    correct = fields.Boolean("Correct")
    answered = fields.Boolean("Answered")
    corona = fields.Boolean("Corona")

class NaiGameAnswer(models.Model):
    _name = 'nai.game.answer'

    game_id = fields.Many2one('nai.game')
    sender = fields.Char('Sender')
    answer = fields.Char("Answer")
    corona = fields.Boolean("Corona")

class NaiGameScore(models.Model):
    _name = 'nai.game.score'

    game_id = fields.Many2one('nai.game')
    sender = fields.Char('Sender')
    avg_time = fields.Float("AverageTime")
    total_correct = fields.Float("Correct")
    total_answered = fields.Float("Answered")
    total_corona = fields.Float("Corona")

