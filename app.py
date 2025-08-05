# -*- coding: utf-8 -*-
"""
Google Form Klonlayıcı - Özel Stiller İçin Yapısal Klonlama

Bu sürüm, Google Form'un görsel kimliğini DEĞİL, yapısal ve anlamsal
içeriğini klonlamak için tasarlanmıştır.

- Google'ın CSS dosyaları KASTEN ALINMAZ. Bu sayede kendi özel stil dosyanızı
  (font, renk, çerçeve vb.) kullanarak formu özgürce şekillendirebilirsiniz.
- Google Form'daki zengin metin (kalın, italik, altı çizili, link, madde imli/numaralı listeler)
  doğru HTML etiketlerine (<b>, <a>, <ul> vb.) dönüştürülür.
- Klonlanan form, bu anlamsal HTML'i içerir ve sizin CSS'inizle stilize edilmeye hazırdır.
- Önceki sürümdeki ham veri gösterme hatası düzeltilmiştir.
"""

import os
import io
import json
import requests
import pandas as pd
from bs4 import BeautifulSoup
from flask import Flask, request, render_template_string, send_file, session
from urllib.parse import unquote
from datetime import datetime

# Flask uygulamasını başlat
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "your-super-secret-key-for-dev")


def analyze_google_form(url: str):
    """
    Verilen Google Form URL'sini analiz eder ve yapısal verilerini çıkarır.
    Bu fonksiyon artık stil bilgilerini (head_html) ÇEKMEZ.
    """
    try:
        headers = {
            'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) '
                           'Chrome/124.0.0.0 Safari/537.36')
        }
        if 'forms.gle/' in url:
            resp = requests.head(url, allow_redirects=True, timeout=10, headers=headers)
            resp.raise_for_status()
            url = resp.url
        
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()

    except requests.RequestException as e:
        return {"error": f"URL alınırken bir hata oluştu: {e}"}

    soup = BeautifulSoup(resp.text, 'html.parser')
    
    # --- Form Yapısını (JSON Verisi) Çek ---
    form_data = {'pages': []}
    for script in soup.find_all('script'):
        if script.string and 'FB_PUBLIC_LOAD_DATA_' in script.string:
            try:
                raw_json_str = script.string.replace('var FB_PUBLIC_LOAD_DATA_ = ', '').rstrip(';')
                data = json.loads(raw_json_str)

                form_info = data[1]
                
                # --- HATA DÜZELTMESİ ---
                # Form başlığı ve açıklaması doğru indekslerden okunuyor.
                # Önceki kodda açıklama yerine tüm soru listesi atanıyordu.
                form_data['title'] = form_info[8] if len(form_info) > 8 and form_info[8] else (form_info[0] or 'İsimsiz Form')
                # Google formda açıklama alanı 7. indexte yer alır.
                form_data['description'] = form_info[7] if len(form_info) > 7 and isinstance(form_info[7], str) else ''
                
                # Soruların bulunduğu liste
                question_list = form_info[1]

                current_page = []
                if data[1][10] and data[1][10][0]:
                     current_page.append({
                        'type': 'E-posta', 'text': 'E-posta Adresi',
                        'description': 'Bu form, e-posta adreslerini toplamak üzere ayarlanmış.',
                        'entry_id': 'emailAddress', 'required': True
                    })
                
                for q in question_list:
                    if not q or not q[0]: continue

                    question = {}
                    q_id, q_text_plain, q_desc_plain, q_type, q_info = q[0], q[1], q[2], q[3], q[4]

                    # Zengin metin içeren başlık ve açıklamayı al.
                    rich_text_info = q[-1] if isinstance(q[-1], list) else []
                    question['text'] = rich_text_info[1] if len(rich_text_info) > 1 and rich_text_info[1] else q_text_plain
                    # Zengin metin açıklama, Google'da düz metin açıklamasından farklı bir yerde olabilir.
                    # İkisini de kontrol ediyoruz.
                    rich_desc = rich_text_info[2] if len(rich_text_info) > 2 and rich_text_info[2] else None
                    question['description'] = rich_desc or q_desc_plain or ''

                    container = soup.find('div', {'data-item-id': str(q_id)})
                    if container:
                        img_tag = container.select_one('.M7eMe-tJHJj-Lg5QKe img, .geS5n img')
                        question['image_url'] = img_tag['src'] if img_tag else None
                    else:
                        question['image_url'] = None

                    if q_info is None:
                        question['type'] = 'Başlık/Medya'
                        current_page.append(question)
                        if len(q) > 8 and q[8]:
                            form_data['pages'].append(current_page)
                            current_page = []
                        continue
                    
                    entry_id = q_info[0][0]
                    question['entry_id'] = f'entry.{entry_id}'
                    question['required'] = bool(q_info[0][2])

                    if q_type == 0: question['type'] = 'Kısa Yanıt'
                    elif q_type == 1: question['type'] = 'Paragraf'
                    elif q_type == 2 or q_type == 4:
                        question['type'] = 'Çoktan Seçmeli' if q_type == 2 else 'Onay Kutuları'
                        question['options'] = []
                        question['has_other'] = False
                        for opt in q_info[0][1]:
                            if not opt: continue
                            if len(opt) > 4 and opt[4]:
                                question['has_other'] = True
                                continue
                            img_url = unquote(opt[5][0]) if len(opt) > 5 and opt[5] else None
                            question['options'].append({'text': opt[0], 'image_url': img_url})
                    elif q_type == 3:
                        question['type'] = 'Açılır Liste'
                        question['options'] = [opt[0] for opt in q_info[0][1] if opt and opt[0]]
                    else: # Diğer tipler şimdilik atlanıyor
                        continue
                        
                    current_page.append(question)
                    
                    if len(q) > 12 and q[12]:
                        form_data['pages'].append(current_page)
                        current_page = []

                if current_page:
                    form_data['pages'].append(current_page)
                
                break 

            except (json.JSONDecodeError, IndexError, TypeError) as e:
                return {"error": f"Form verisi ayrıştırılırken bir hata oluştu: {e}."}
    
    if not form_data['pages'] or not any(form_data['pages']):
        return {"error": "Formda analiz edilecek soru bulunamadı veya form yapısı okunamadı."}

    # Fonksiyon artık sadece form_data döndürüyor.
    return {"form_data": form_data}


# --- HTML Şablonu (Kendi Stillerinizle) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Özel Stilli Form Klonu</title>
    <!-- 
      BURASI SİZİN STİL ALANINIZ.
      Google'ın CSS'i artık burada değil. Bu sayede aşağıdaki stiller ve
      kendi ekleyeceğiniz stiller tam olarak çalışacaktır.
    -->
    <style>
        /* Genel Sayfa Stilleri - Kendi stilinizi buraya yazın */
        @import url('https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700&display=swap');
        
        body { 
            font-family: 'Nunito', sans-serif; 
            background-color: #f0f2f5; 
            color: #333; 
            margin: 0; 
            padding: 1.5rem; 
        }
        .main-container { 
            max-width: 750px; 
            margin: 0 auto; 
            background-color: #ffffff; 
            padding: 2.5rem; 
            border-radius: 12px; 
            box-shadow: 0 6px 20px rgba(0,0,0,0.08);
            border-top: 5px solid #6c5ce7;
        }
        
        /* Semantik HTML Etiketlerini Stilize Etme (Amacınızı kanıtlamak için) */
        b, strong {
            /* Google'dan gelen kalın bilgisi bu stile göre renklenecek */
            color: #6c5ce7; 
            font-weight: 700;
        }
        i, em {
            /* Google'dan gelen italik bilgisi bu stile göre renklenecek */
            color: #0984e3;
        }
        u {
           /* Altı çizili metinler için özel stil */
           text-decoration-color: #fd79a8;
           text-decoration-thickness: 2px;
        }
        a {
            /* Linkler için kendi stiliniz */
            color: #d63031;
            font-weight: 600;
            text-decoration: none;
        }
        a:hover {
            text-decoration: underline;
        }
        ul, ol {
            /* Listeler için özel stil */
            background-color: #fafafa;
            border-left: 3px solid #6c5ce7;
            padding: 1rem 1rem 1rem 2.5rem; /* Sol padding artırıldı */
            margin: 1rem 0;
            border-radius: 0 8px 8px 0;
        }

        /* Form Elemanları Stilleri */
        .form-title { font-size: 2.2rem; font-weight: 700; color: #333; border-bottom: 2px solid #eee; padding-bottom: 1rem; margin-bottom: 1rem; }
        .form-description { font-size: 1rem; color: #555; margin-bottom: 2.5rem; line-height: 1.6; }
        .question-block { margin-bottom: 2rem; padding: 1.5rem; border: 1px solid #e0e0e0; border-radius: 8px; transition: box-shadow 0.2s; }
        .question-block:focus-within { border-color: #6c5ce7; box-shadow: 0 0 0 3px rgba(108, 92, 231, 0.2); }
        .question-text { font-weight: 600; font-size: 1.1rem; margin-bottom: 0.5rem; }
        .required-star { color: #d63031; font-size: 1.2rem; }
        input[type="text"], input[type="email"], textarea, select { width: 100%; padding: 0.8rem; border: 1px solid #ccc; border-radius: 6px; box-sizing: border-box; font-family: 'Nunito', sans-serif; transition: border-color 0.2s; }
        input[type="text"]:focus, input[type="email"]:focus, textarea:focus, select:focus { border-color: #6c5ce7; outline: none; }
        .btn { display: inline-block; font-weight: 600; color: #fff; background-image: linear-gradient(to right, #6c5ce7, #a29bfe); border: none; padding: 0.9rem 1.8rem; font-size: 1rem; border-radius: 6px; cursor: pointer; text-align: center; text-decoration: none; margin-top: 1rem; transition: transform 0.2s; }
        .btn:hover { transform: translateY(-2px); }
        .error-message { margin-top: 1rem; color: #d63031; background-color: #ffdddd; border: 1px solid #d63031; padding: 1rem; border-radius: 4px; }
    </style>
</head>
<body>
  <div class="main-container">
    <h1>Google Form Klonlayıcı</h1>
    <form method="post" action="/">
      <input type="text" name="url" placeholder="Klonlamak istediğiniz Google Form URL'sini yapıştırın" required>
      <button class="btn" style="background-image: linear-gradient(to right, #0984e3, #74b9ff);">Formu Oluştur</button>
    </form>

    {% if error %}
      <div class="error-message"><strong>Hata:</strong> {{ error }}</div>
    {% endif %}

    {% if form_data %}
      <hr style="margin: 2rem 0; border: 0; border-top: 1px solid #eee;">
      <div class="form-title">{{ form_data.title | safe }}</div>
      {% if form_data.description %}
        <div class="form-description">{{ form_data.description | safe }}</div>
      {% endif %}
      
      <form method="post" action="/submit" enctype="multipart/form-data">
        {% for page in form_data.pages %}
            {% for q in page %}
                <div class="question-block">
                  <div class="question-text">{{ q.text | safe }} {% if q.required %}<span class="required-star">*</span>{% endif %}</div>
                  {% if q.description %}<div class="question-description">{{ q.description | safe }}</div>{% endif %}
                  {% if q.image_url %}<img src="{{ q.image_url }}" style="max-width:100%; border-radius:8px; margin-top:1rem;">{% endif %}

                  {% if q.type == 'Kısa Yanıt' %}<input type="text" name="{{ q.entry_id }}" {% if q.required %}required{% endif %}>
                  {% elif q.type == 'E-posta' %}<input type="email" name="{{ q.entry_id }}" {% if q.required %}required{% endif %}>
                  {% elif q.type == 'Paragraf' %}<textarea name="{{ q.entry_id }}" {% if q.required %}required{% endif %}></textarea>
                  {% elif q.type == 'Çoktan Seçmeli' or q.type == 'Onay Kutuları' %}
                    <div>
                      {% for opt in q.options %}<label style="display:block; margin-bottom:0.5rem;"><input type="{{ 'radio' if q.type == 'Çoktan Seçmeli' else 'checkbox' }}" name="{{ q.entry_id }}" value="{{ opt.text }}"> {{ opt.text | safe }}</label>{% endfor %}
                      {% if q.has_other %}<label style="display:flex; align-items:center; margin-top:0.5rem;"><input type="{{ 'radio' if q.type == 'Çoktan Seçmeli' else 'checkbox' }}" name="{{ q.entry_id }}" value="__other_option__"> Diğer: <input type="text" name="{{ q.entry_id }}.other_option_response" style="width:auto; flex-grow:1;"></label>{% endif %}
                    </div>
                  {% elif q.type == 'Açılır Liste' %}
                    <select name="{{ q.entry_id }}" {% if q.required %}required{% endif %}><option value="" disabled selected>Seçin...</option>{% for opt in q.options %}<option value="{{ opt | safe }}">{{ opt | safe }}</option>{% endfor %}</select>
                  {% endif %}
                </div>
            {% endfor %}
        {% endfor %}
        <button type="submit" class="btn">Yanıtları Excel Olarak İndir</button>
      </form>
    {% endif %}
  </div>
</body>
</html>
"""

# --- Flask Rotaları ---

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        url = request.form.get('url', '').strip()
        if not url or ('docs.google.com/forms' not in url and 'forms.gle' not in url):
            # head_html artık gönderilmiyor.
            return render_template_string(HTML_TEMPLATE, error='Lütfen geçerli bir Google Form URL\'si girin.', form_data=None)
        
        result = analyze_google_form(url)
        if 'error' in result:
             # head_html artık gönderilmiyor.
            return render_template_string(HTML_TEMPLATE, error=result['error'], form_data=None)
        
        session['form_structure'] = result['form_data']
        
         # head_html artık gönderilmiyor.
        return render_template_string(HTML_TEMPLATE, error=None, form_data=result['form_data'])
    
    # head_html artık gönderilmiyor.
    return render_template_string(HTML_TEMPLATE, error=None, form_data=None)


@app.route('/submit', methods=['POST'])
def submit():
    form_structure = session.get('form_structure')
    if not form_structure:
        return 'Hata: Form yapısı oturumda bulunamadı. Lütfen formu tekrar oluşturun.', 400

    answers = request.form
    results = []
    
    for page in form_structure.get('pages', []):
        for q in page:
            if q.get('type') in ['Başlık/Medya']: continue
            entry_id = q.get('entry_id')
            if not entry_id: continue
            
            question_text = BeautifulSoup(q.get('text',''), 'html.parser').get_text(separator=' ', strip=True)
            answer_text = 'Yanıtlanmadı'

            if q.get('type') == 'Onay Kutuları':
                values = answers.getlist(entry_id)
                final_answers = []
                if '__other_option__' in values:
                    values.remove('__other_option__')
                    other_text = answers.get(f"{entry_id}.other_option_response", '').strip()
                    final_answers.append(f"Diğer: {other_text}" if other_text else "Diğer (boş)")
                final_answers.extend(values)
                answer_text = ', '.join(final_answers) if final_answers else 'Yanıtlanmadı'
            elif q.get('type') == 'Çoktan Seçmeli':
                value = answers.get(entry_id)
                if value == '__other_option__':
                    other_text = answers.get(f"{entry_id}.other_option_response", '').strip()
                    answer_text = f"Diğer: {other_text}" if other_text else "Diğer (boş)"
                else:
                    answer_text = value or 'Yanıtlanmadı'
            else:
                answer_text = answers.get(entry_id, '').strip() or 'Yanıtlanmadı'
            
            results.append({'Soru': question_text, 'Cevap': answer_text})
    
    df = pd.DataFrame(results)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Form Yanıtları')
    buf.seek(0)
    
    return send_file(
        buf,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'form_yanitlari_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    )

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
