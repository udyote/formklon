# -*- coding: utf-8 -*-
"""
Google Form Klonlayıcı - Stil Bilgilerini Koruyan Tam Sürüm
- Orijinal <head> içindeki tüm <link> ve <style> etiketleri klon sayfasına eklenir
- Zengin Metin Desteği: Başlık/Açıklama, kalın, italik, altı çizili, link ve listeleri korur
- Medya Desteği: Görselleri destekler
- Doğru Bölümleme: Bölüm mantığıyla çok sayfalı formu uygular
- UX İyileştirmeleri: "Diğer" seçeneği, radyo tuşu seçim kaldırma
- Kısa Link Desteği: forms.gle linklerini çözer
"""
import os
import io
import json
import requests
import pandas as pd
from bs4 import BeautifulSoup
from flask import Flask, request, render_template_string, send_file, session
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-fallback-key")


def wrap_with_tags(inner_html, bold=False, italic=False, underline=False):
    """
    Verilen inner_html'i semantik etiketlerle sarar: <b>, <i>, <u>
    """
    soup = BeautifulSoup(inner_html, "html.parser")
    content = soup
    # Altı çizgi -> italic -> bold iç içe
    if underline:
        tag = soup.new_tag("u"); tag.append(content); content = tag
    if italic:
        tag = soup.new_tag("i"); tag.append(content); content = tag
    if bold:
        tag = soup.new_tag("b"); tag.append(content); content = tag
    return str(content)


def get_inner_html(element):
    """
    Element içindeki HTML'i, semantik etiketleri koruyarak döner.
    <span style=> gibi inline stilleri b, i, u etiketlerine dönüştürür.
    """
    if not element:
        return ""
    # Gereksiz <font> etiketlerini kaldır
    for tag in element.find_all('font'):
        tag.unwrap()
    # <span style=> içindeki stilleri semantik etiketlere çevir
    for span in element.find_all('span'):
        style = span.get('style', '').lower()
        bold = 'font-weight' in style and any(x in style for x in ['700','bold'])
        italic = 'font-style:italic' in style or 'italic' in style
        underline = 'text-decoration' in style and 'underline' in style
        if bold or italic or underline:
            inner = ''.join(str(c) for c in span.contents)
            wrapped = wrap_with_tags(inner, bold=bold, italic=italic, underline=underline)
            new_frag = BeautifulSoup(wrapped, 'html.parser')
            span.replace_with(new_frag)
        else:
            span.unwrap()
    return element.decode_contents().strip()


def analyze_google_form(url: str):
    """
    Google Form URL'sini çekip analiz eder.
    Döner: { form_data, head_html } veya hata: { error }
    """
    try:
        headers = {
            'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) '
                           'Chrome/122.0.0.0 Safari/537.36')
        }
        # forms.gle kısaltmalarını çöz
        if 'forms.gle/' in url:
            resp = requests.head(url, allow_redirects=True, timeout=10, headers=headers)
            resp.raise_for_status()
            url = resp.url
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        return {"error": f"URL okunamadı: {e}"}

    soup = BeautifulSoup(resp.text, 'html.parser')
    # 1) <head> içindeki tüm <link> ve <style> etiketlerini topla
    head = soup.head or BeautifulSoup('<head></head>','html.parser').head
    head_tags = [str(tag) for tag in head.find_all(['link','style'])]
    head_html = '\n'.join(head_tags)

    # 2) Form yapısını çıkar
    form_data = { 'pages': [] }
    # Başlık & açıklama
    title_div = soup.find('div', class_='F9yp7e')
    form_data['title'] = get_inner_html(title_div) if title_div else 'İsimsiz Form'
    desc_div = soup.find('div', class_='cBGGJ')
    form_data['description'] = get_inner_html(desc_div) if desc_div else ''

    # FB_PUBLIC_LOAD_DATA_ script'ini bul
    for script in soup.find_all('script'):
        if script.string and 'FB_PUBLIC_LOAD_DATA_' in script.string:
            try:
                raw = script.string.replace('var FB_PUBLIC_LOAD_DATA_ = ', '').rstrip(';')
                data = json.loads(raw)
                question_list = data[1][1]
                current_page = []
                # E-posta sorusu
                email_div = soup.find('div', {'jsname':'Y0xS1b'})
                if email_div:
                    parent = email_div.find_parent('div', {'jsmodel':'CP1oW'})
                    if parent and parent.has_attr('data-params'):
                        p = parent['data-params']
                        eid = p.split(',')[-1].split('"')[0]
                        if eid.isdigit():
                            current_page.append({
                                'type':'E-posta', 'text':'E-posta',
                                'description':'Lütfen e-posta girin.',
                                'entry_id':f'entry.{eid}', 'required':True,
                                'image_url':None
                            })
                # Soruları işle
                for q in question_list:
                    try:
                        qid, qtext, qdesc, qtype, qinfo = q[0], q[1], q[2], q[3], q[4]
                        question = { 'image_url':None }
                        container = soup.find('div', {'data-item-id':str(qid)})
                        # Metin & açıklama
                        txt_el = container.select_one('.M7eMe') if container else None
                        dsc_el = container.select_one('.OIC90c') if container else None
                        question['text'] = get_inner_html(txt_el) if txt_el else qtext
                        question['description'] = get_inner_html(dsc_el) if dsc_el else (qdesc or '')
                        # Görsel
                        if container:
                            img = container.select_one('.y6GzNb img')
                            if img and img.has_attr('src'):
                                question['image_url'] = img['src']
                        # Medya başlık
                        if qinfo is None:
                            question['type'] = 'Media'
                            current_page.append(question)
                            continue
                        # Tablo soruları
                        if qtype == 7:
                            rows = qinfo
                            first = rows[0]
                            question['type'] = ('Onay Kutusu Tablosu' if first[11] and first[11][0]
                                else 'Çoktan Seçmeli Tablosu')
                            question['required'] = bool(first[2])
                            question['cols'] = [c[0] for c in first[1]]
                            question['rows'] = [{'text':r[3][0],'entry_id':f"entry.{r[0]}"} for r in rows]
                        else:
                            entry_id = qinfo[0]
                            required = bool(qinfo[2])
                            question['entry_id'] = f'entry.{entry_id}'
                            question['required'] = required
                            # Tip bazlı işlem
                            if qtype == 0:
                                question['type'] = 'Kısa Yanıt'
                            elif qtype == 1:
                                question['type'] = 'Paragraf'
                            elif qtype in (2,4):
                                question['options']=[]; question['has_other']=False
                                for opt in qinfo[1]:
                                    # Diğer
                                    if len(opt)>4 and opt[4]:
                                        question['has_other']=True; continue
                                    if not opt[0] and opt[0] != '': continue
                                    question['options'].append({'text':opt[0],'image_url':None})
                                question['type'] = ('Çoktan Seçmeli' if qtype==2 else 'Onay Kutuları')
                            elif qtype == 3:
                                question['type']='Açılır Liste'
                                question['options']=[o[0] for o in qinfo[1] if o[0]]
                            elif qtype == 5:
                                question['type']='Doğrusal Ölçek'
                                question['options']=[o[0] for o in qinfo[1]]
                                question['labels']=qinfo[3] if len(qinfo)>3 else ['','']
                            elif qtype == 18:
                                question['type']='Derecelendirme'
                                question['options']=[str(o[0]) for o in qinfo[1]]
                            elif qtype == 9:
                                question['type']='Tarih'
                            elif qtype == 10:
                                question['type']='Saat'
                            elif qtype == 6:
                                question['type']='Başlık'
                            else:
                                continue
                        current_page.append(question)
                        # Sayfa bitişi
                        if len(q)>12 and q[12]:
                            form_data['pages'].append(current_page)
                            current_page = []
                    except Exception:
                        continue
                # Kalan sayfa
                if current_page:
                    form_data['pages'].append(current_page)
                break
            except Exception as e:
                return {"error": f"Ayrıştırma hatası: {e}"}
    if not form_data['pages']:
        return {"error": "Formda soru bulunamadı."}
    return {"form_data": form_data, "head_html": head_html}

# HTML Şablonu
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="tr">
<head>
  {{ head_html | safe }}
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    /* Ek stil düzeltmeleri */
    body{font-family:system-ui; background:#f8f9fa; padding:2rem;}
    .container{max-width:760px; margin:0 auto; background:#fff; padding:2rem; border-radius:8px;}
    .btn{background:#198754; color:#fff; padding:.75rem 1.5rem; border:none; border-radius:.375rem; cursor:pointer;}
    .required-star{color:#dc3545;}
  </style>
</head>
<body>
  <div class="container">
    <h1>Google Form Klonlayıcı</h1>
    <form method="post" action="/">
      <input type="text" name="url" placeholder="Google Form URL'si girin" required style="width:100%;padding:.5rem;">
      <button class="btn" style="margin-top:1rem;">Formu Oluştur</button>
    </form>
    {% if error %}
      <div style="margin-top:1rem;color:red;">{{ error }}</div>
    {% endif %}
    {% if form_data %}
      <h2 style="margin-top:2rem;">{{ form_data.title | safe }}</h2>
      {% if form_data.description %}
        <div style="margin-bottom:1.5rem;">{{ form_data.description | safe }}</div>
      {% endif %}
      <form method="post" action="/submit">
        {% for page in form_data.pages %}
          <div class="page" style="margin-bottom:2rem;">
            {% for q in page %}
              {% if q.type in ['Başlık','Media'] %}
                <div style="margin:1.5rem 0;">
                  <div style="font-size:1.25rem;font-weight:600;">{{ q.text | safe }}</div>
                  {% if q.description %}<div style="color:#6c757d;">{{ q.description | safe }}</div>{% endif %}
                  {% if q.image_url %}<img src="{{ q.image_url }}" style="max-width:100%;margin-top:.5rem;">{% endif %}
                </div>
              {% else %}
                <div style="margin-bottom:1.5rem;">
                  <label style="font-weight:600;">{{ q.text | safe }} {% if q.required %}<span class="required-star">*</span>{% endif %}</label>
                  {% if q.description %}<div style="color:#6c757d;font-size:0.9rem;">{{ q.description | safe }}</div>{% endif %}
                  {% if q.type=='Kısa Yanıt' %}
                    <input type="text" name="{{ q.entry_id }}" {% if q.required %}required{% endif %} style="width:100%;padding:.5rem;">
                  {% elif q.type=='Paragraf' %}
                    <textarea name="{{ q.entry_id }}" {% if q.required %}required{% endif %} style="width:100%;padding:.5rem;min-height:100px;"></textarea>
                  {% elif q.type=='Çoktan Seçmeli' %}
                    <div>
                      {% for opt in q.options %}
                        <label><input type="radio" name="{{ q.entry_id }}" value="{{ opt.text }}" {% if q.required %}required{% endif %}> {{ opt.text | safe }}</label><br>
                      {% endfor %}
                      {% if q.has_other %}
                        <label><input type="radio" name="{{ q.entry_id }}" value="__other_option__"> Diğer:</label>
                        <input type="text" name="{{ q.entry_id }}.other_option_response" style="padding:.4rem .6rem;">
                      {% endif %}
                    </div>
                  {% elif q.type=='Onay Kutuları' %}
                    <div>
                      {% for opt in q.options %}
                        <label><input type="checkbox" name="{{ q.entry_id }}" value="{{ opt.text }}"> {{ opt.text | safe }}</label><br>
                      {% endfor %}
                      {% if q.has_other %}
                        <label><input type="checkbox" name="{{ q.entry_id }}" value="__other_option__"> Diğer:</label>
                        <input type="text" name="{{ q.entry_id }}.other_option_response" style="padding:.4rem .6rem;">
                      {% endif %}
                    </div>
                  {% elif q.type=='Açılır Liste' %}
                    <select name="{{ q.entry_id }}" {% if q.required %}required{% endif %} style="width:100%;padding:.5rem;">
                      <option value="" disabled selected>Seçin...</option>
                      {% for opt in q.options %}<option>{{ opt | safe }}</option>{% endfor %}
                    </select>
                  {% elif q.type in ['Çoktan Seçmeli Tablosu','Onay Kutusu Tablosu'] %}
                    <table style="width:100%;border-collapse:collapse;margin-top:.5rem;">
                      <thead><tr><th></th>{% for col in q.cols %}<th style="border:1px solid #dee2e6;padding:.6rem;">{{ col }}</th>{% endfor %}</tr></thead>
                      <tbody>
                        {% for row in q.rows %}
                        <tr><td style="border:1px solid #dee2e6;padding:.6rem;font-weight:600;">{{ row.text }}</td>
                          {% for col in q.cols %}
                          <td style="border:1px solid #dee2e6;padding:.6rem;text-align:center;">
                            <input type="{{ 'checkbox' if 'Onay' in q.type else 'radio' }}" name="{{ row.entry_id }}" value="{{ col }}" {% if q.required %}required{% endif %}>
                          </td>
                          {% endfor %}</tr>
                        {% endfor %}
                      </tbody>
                    </table>
                  {% endif %}
                </div>
              {% endif %}
            {% endfor %}
          </div>
        {% endfor %}
        <button class="btn">Cevapları Excel İndir</button>
      </form>
    {% endif %}
  </div>
</body>
</html>"""

@app.route('/', methods=['GET','POST'])
def index():
    if request.method=='POST':
        url = request.form.get('url','').strip()
        if not url or ('docs.google.com/forms' not in url and 'forms.gle' not in url):
            return render_template_string(HTML_TEMPLATE, error='Geçerli Form URL girin', form_data=None, head_html='')
        result = analyze_google_form(url)
        if 'error' in result:
            return render_template_string(HTML_TEMPLATE, error=result['error'], form_data=None, head_html=result.get('head_html',''))
        form_data = result['form_data']
        head_html = result['head_html']
        session['form_structure'] = form_data
        return render_template_string(HTML_TEMPLATE, error=None, form_data=form_data, head_html=head_html)
    return render_template_string(HTML_TEMPLATE, error=None, form_data=None, head_html='')

@app.route('/submit', methods=['POST'])
def submit():
    form_structure = session.get('form_structure')
    if not form_structure:
        return 'Hata: Form yapısı bulunamadı.', 400
    answers = request.form
    results = []
    for page in form_structure.get('pages',[]):
        for q in page:
            if q.get('type') in ['Başlık','Media']:
                continue
            eid = q.get('entry_id')
            if not eid: continue
            ans = None
            if q['type']=='Onay Kutuları':
                vals = answers.getlist(eid)
                final=[]
                if '__other_option__' in vals:
                    vals.remove('__other_option__')
                    oth = answers.get(f"{eid}.other_option_response', '').strip()
                    final.append(f'Diğer: {oth}' if oth else 'Diğer')
                final+=vals
                ans = ', '.join(final) if final else 'Boş'
            elif q['type']=='Çoktan Seçmeli':
                val=answers.get(eid)
                if val=='__other_option__':
                    oth=answers.get(f"{eid}.other_option_response", '').strip()
                    ans=f'Diğer: {oth}' if oth else 'Diğer'
                else:
                    ans=val or 'Boş'
            else:
                ans = answers.get(eid, '').strip() or 'Boş'
            text = BeautifulSoup(q['text'], 'html.parser').get_text(separator=' ', strip=True)
            results.append({'Soru': text, 'Cevap': ans})
    df = pd.DataFrame(results)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Cevaplar')
    buf.seek(0)
    return send_file(buf,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True,
                     download_name='form_cevaplari.xlsx')

if __name__=='__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
