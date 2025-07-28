TypeError: 'builtin_function_or_method' object is not iterable
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "<template>", line 61, in top-level template code```

Bu hata, Jinja2 şablonunuzun 61. satırında, yani `{% for opt in item.options %}` döngüsünde meydana geliyor. `TypeError: 'builtin_function_or_method' object is not iterable` mesajı, `item.options` değişkeninin bir liste (veya başka bir yinelenebilir nesne) olması beklenirken, aslında bir "yerleşik fonksiyon veya metot" (örneğin `list` fonksiyonunun kendisi gibi) olduğunu gösterir.

Python kodunuzdaki `analyze_google_form` fonksiyonunda `question['options']` değerini atadığınız tüm yerleri kontrol ettim. Her durumda `[]` boş bir liste veya liste kapsaması (list comprehension) kullanılarak liste atanmış durumda. Bu, Python tarafında doğrudan bir fonksiyon ataması yapmadığınızı gösteriyor.

Ancak, Jinja2 şablonu, `item.type` değeri `'Çoktan Seçmeli'` (veya seçenekleri olan diğer tipler) olduğunda `item.options`'ın yinelenebilir bir şey (liste gibi) olmasını bekler. Eğer bir nedenden dolayı (örneğin, çok nadir ve beklenmedik bir Google Form yapısı nedeniyle), `item.options` anahtarı bir `list` nesnesi yerine Python'ın yerleşik `list` *fonksiyonuna* referans verirse bu hata oluşur. Bu durum genellikle bir değişkenin yanlışlıkla bir fonksiyon objesine eşitlenmesiyle (`my_var = list` yerine `my_var = []` olması gerekirken yanlışlıkla `my_var = list` gibi) ortaya çıkar. Kodunuzda bu tür bir atama görünmüyor, bu yüzden sorun daha karmaşık bir senaryodan kaynaklanıyor olabilir.

**Çözüm:**

Sorunun temel nedeni hala net olmasa da (çünkü JSON verisi doğrudan fonksiyon içeremez), bu hatayı engelleyebilir ve uygulamanın çökmesini önleyebiliriz. Bunu, Jinja2 şablonunda `item.options` üzerinde döngü yapmadan önce, bu değişkenin gerçekten yinelenebilir (iterable) olup olmadığını kontrol ederek yapabiliriz.

Aşağıda, `HTML_TEMPLATE` içinde `item.options` kullanılan tüm yerlere bu kontrolü ekleyerek güncellenmiş kodu bulabilirsiniz. Bu değişiklik, hata oluştuğunda uygulamanın çökmesi yerine, kullanıcıya sorunun kaynağını belirten bir uyarı mesajı göstermesini sağlayacaktır.

```python
import os
import io
import json
import requests
import pandas as pd
from bs4 import BeautifulSoup
from flask import Flask, request, render_template_string, send_file, session
from markupsafe import Markup  # Import Markup for rendering raw HTML safely

app = Flask(__name__)
# SECRET_KEY .env'den veya ortam değişkeninden okunur, yoksa fallback kullanılır
app.secret_key = os.environ.get("SECRET_KEY", "dev-fallback-key-please-change-in-production")

def analyze_google_form(url: str):
    """Google Form URL'sini parse ederek soru yapısını döndürür."""
    try:
        headers = {
            'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36')
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        return {"error": f"URL okunamadı. Geçerli bir Google Form linki girin. Hata: {e}"}

    soup = BeautifulSoup(response.text, 'html.parser')
    form_data = {"items": []}  # Tüm form öğeleri (sorular, bölümler, resimler) burada saklanacak

    # --- 1. Genel Form Başlığı ve Açıklaması ---
    # Bu kısımlar genellikle formun en başında bulunur ve doğrudan HTML'den çekilir.
    title_elem = soup.find('div', class_='F9yp7e')
    form_data['title'] = Markup(title_elem.decode_contents()) if title_elem else "İsimsiz Form"

    description_elem = soup.find('div', class_='cBGGJ')
    form_data['description'] = Markup(description_elem.decode_contents()) if description_elem else ""

    # --- 2. FB_PUBLIC_LOAD_DATA_ JSON verisini çıkar (soru mantığı, entry ID'leri, seçenekler vb. için) ---
    json_items_map = {}
    for script in soup.find_all('script'):
        if script.string and 'FB_PUBLIC_LOAD_DATA_' in script.string:
            try:
                raw = script.string.replace('var FB_PUBLIC_LOAD_DATA_ = ', '').rstrip(';')
                data = json.loads(raw)
                # data[1][1] form öğelerinin ana listesini içerir (sorular, bölümler vb.)
                if len(data) > 1 and len(data[1]) > 1 and data[1][1]:
                    for item_json in data[1][1]:
                        if item_json and len(item_json) > 0:
                            json_items_map[item_json[0]] = item_json  # item_id'yi JSON verisiyle eşleştir
                break
            except (json.JSONDecodeError, IndexError, TypeError) as e:
                print(f"Hata: FB_PUBLIC_LOAD_DATA_ ayrıştırılırken bir sorun oluştu: {e}")
                return {"error": f"Form verileri ayrıştırılamadı (format değişmiş olabilir). Hata: {e}"}

    # --- 3. HTML form öğesi kapsayıcılarını (`OxAavc`) dolaşarak görünür yapıyı ve zengin içeriği al ---
    # Bu kapsayıcıların data-item-id özelliği, JSON verisine bağlanır
    for item_div in soup.find_all('div', {'jsname': 'ibnC6b', 'data-item-id': True}):
        try:
            item_id = int(item_div.get('data-item-id'))
            item_json = json_items_map.get(item_id)

            # Bazı öğeler JSON'da doğrudan bir karşılığı olmayabilir (örn: sadece düzen divleri)
            # Ancak, bir 'OxAavc' bloğu genellikle bir form öğesidir.
            # Burada, JSON'dan bilgi alamadığımız ancak HTML'de görünen resim bloklarını ele alıyoruz.
            if not item_json:
                image_elem = item_div.find('img', class_='HxhGpf')
                # Eğer içinde img var ve bir başlık veya açıklama bölümü değilse (sezgisel)
                if image_elem and not item_div.find('div', class_='meSK8') and not item_div.find('div', class_='spb5Rd'):
                    img_item = {'type': 'Image'}
                    caption_elem = item_div.find('span', class_='M7eMe')  # Resim başlığı/açıklaması
                    img_item['title'] = Markup(caption_elem.decode_contents()) if caption_elem else ""
                    img_item['image_url'] = image_elem.get('src')
                    form_data['items'].append(img_item)
                continue  # JSON verisi olmayan diğer öğeleri atla

            item_type_id = item_json[3]  # JSON verisindeki tip ID'si

            # HTML yapısına göre başlık/metin öğelerini al
            html_title_elem = item_div.find('div', class_='meSK8')
            html_description_elem = item_div.find('div', class_='spb5Rd')
            
            # --- Bölüm/Başlık/Açıklama Bloklarını Yönet (Tip 12) ---
            if item_type_id == 12:
                section = {'type': 'Section'}
                section['title'] = Markup(html_title_elem.decode_contents()) if html_title_elem else ""
                section['description'] = Markup(html_description_elem.decode_contents()) if html_description_elem else ""
                
                # Bölüm içindeki resim
                image_elem = item_div.find('img', class_='HxhGpf')
                if image_elem:
                    section['image_url'] = image_elem.get('src')
                
                form_data['items'].append(section)
                continue
            
            # --- Soruları Yönet (Tipler 0-10, 18, 7) ---
            # Ortak soru özelliklerini başlat
            question = {'type': 'Question'}
            # Zengin metin için HTML'i tercih et, yoksa JSON'dan ham metni al
            question['text'] = Markup(html_title_elem.decode_contents()) if html_title_elem else item_json[1]
            
            # item_json yapısına güvenli erişim için kontrol
            q_info = item_json[4][0] if len(item_json) > 4 and item_json[4] and len(item_json[4]) > 0 else None
            
            question['entry_id'] = f"entry.{q_info[0]}" if q_info and len(q_info) > 0 else None
            question['required'] = bool(q_info[2]) if q_info and len(q_info) > 2 else False

            # Matris Tablosu (tip 7)
            if item_type_id == 7:
                question_data_from_json = item_json[4][0]
                
                is_checkbox_grid = False
                # Checkbox veya radio grid'i belirleme yapısı karmaşık olabilir.
                # Genellikle item_json'daki belirli bir bayrağa bakılır.
                # Örn: q_info[4] veya q_info[5] checkbox grid'i işaret edebilir.
                if len(question_data_from_json) > 4 and question_data_from_json[4]: 
                    is_checkbox_grid = True

                question['type'] = 'Onay Kutusu Tablosu' if is_checkbox_grid else 'Çoktan Seçmeli Tablo'
                question['cols'] = [c[0] for c in question_data_from_json[1]] if len(question_data_from_json) > 1 and question_data_from_json[1] else []
                
                parsed_rows = []
                # Izgara sorularının satırları genellikle item_json[1][1] içinde entry_id ve metin içerir.
                if len(item_json) > 1 and item_json[1] and len(item_json[1]) > 1 and item_json[1][1]:
                    for r_data in item_json[1][1]:
                        if len(r_data) > 3 and r_data[0] and r_data[3] and r_data[3][0]:
                            parsed_rows.append({'text': Markup(r_data[3][0]), 'entry_id': f"entry.{r_data[0]}"})
                question['rows'] = parsed_rows
                form_data['items'].append(question)
                continue

            # Diğer soru tipleri
            if item_type_id == 0:
                question['type'] = 'Kısa Yanıt'
            elif item_type_id == 1:
                question['type'] = 'Paragraf'
            elif item_type_id in (2, 4):  # Çoktan Seçmeli (radio), Onay Kutuları (checkbox)
                question['options'] = [] # Her zaman boş bir liste olarak başlat
                question['has_other'] = False
                if q_info and len(q_info) > 1 and q_info[1] and isinstance(q_info[1], list):  # Seçenekler dizisi ve liste olduğundan emin ol
                    for opt in q_info[1]:
                        option_dict = {'text': Markup(opt[0]) if opt and len(opt) > 0 and opt[0] else ""}
                        # Seçenek verisinde resim URL'sini kontrol et (örn: opt[5][0][0] veya opt[6][0][0])
                        if len(opt) > 5 and opt[5] and len(opt[5]) > 0 and opt[5][0] and len(opt[5][0]) > 0:
                            option_dict['image_url'] = opt[5][0][0]
                        elif len(opt) > 6 and opt[6] and len(opt[6]) > 0 and opt[6][0] and len(opt[6][0]) > 0:
                            option_dict['image_url'] = opt[6][0][0]  # Alternatif resim yolu

                        if len(opt) > 4 and opt[4]:  # "Diğer" seçeneği bayrağını kontrol et
                            question['has_other'] = True
                        else:
                            question['options'].append(option_dict)
                question['type'] = 'Çoktan Seçmeli' if item_type_id == 2 else 'Onay Kutuları'
            elif item_type_id == 3:
                question['type'] = 'Açılır Liste'
                question['options'] = [{'text': Markup(o[0])} for o in q_info[1] if o and len(o) > 0 and o[0] and isinstance(q_info[1], list)] if q_info and len(q_info) > 1 and isinstance(q_info[1], list) else []
            elif item_type_id == 5:
                question['type'] = 'Doğrusal Ölçek'
                question['options'] = [{'text': Markup(str(o[0]))} for o in q_info[1] if isinstance(q_info[1], list)] if q_info and len(q_info) > 1 and isinstance(q_info[1], list) else []
                question['labels'] = [Markup(q_info[3][0]) if q_info and len(q_info) > 3 and q_info[3] and len(q_info[3]) > 0 and q_info[3][0] else "",
                                      Markup(q_info[3][1]) if q_info and len(q_info) > 3 and q_info[3] and len(q_info[3]) > 1 and q_info[3][1] else ""]
            elif item_type_id == 18:
                question['type'] = 'Derecelendirme'
                question['options'] = [{'text': Markup(str(o[0]))} for o in q_info[1] if isinstance(q_info[1], list)] if q_info and len(q_info) > 1 and isinstance(q_info[1], list) else []
            elif item_type_id == 9:
                question['type'] = 'Tarih'
            elif item_type_id == 10:
                question['type'] = 'Saat'
            else:
                continue  # Bilinmeyen/ele alınmayan soru tipi
            
            form_data['items'].append(question)
        except Exception as e:
            print(f"Hata: item_id {item_id} işlenirken sorun oluştu: {e}")
            continue


    # Opsiyonel: E-posta alanı - Bu genellikle kullanıcı tarafından eklenen bir soru değil, otomatik toplanan bir alandır.
    # Bu alan, eğer zaten bir soru olarak eklenmemişse, ayrı olarak ele alınır.
    email_input = soup.find('input', type='email')
    if email_input:
        parent = email_input.find_parent('div', {'jsmodel': 'CP1oW'})
        if parent and parent.has_attr('data-params'):
            try:
                p = parent['data-params']
                entry_id_part = p.split(',')[-1].split('"')[0]
                if entry_id_part.isdigit():
                    email_entry_id = f'entry.{entry_id_part}'
                    # Eğer bu e-posta sorusu zaten öğeler listesinde varsa, tekrar ekleme
                    email_exists = any(
                        (item.get('type') == 'Question' and item.get('entry_id') == email_entry_id) or
                        item.get('original_type') == 'E-posta'
                        for item in form_data['items']
                    )
                    if not email_exists:
                        # Formun en başına ekle (genellikle Google Forms'ta en başta görünür)
                        form_data['items'].insert(0, {
                            'type': 'Question',  # Bir soru öğesi olarak işaretle
                            'text': 'E-posta',
                            'original_type': 'E-posta',  # Google Forms tipini korumak için farklı bir anahtar kullan
                            'entry_id': email_entry_id,
                            'required': True
                        })
            except Exception:
                pass

    if not form_data['items'] and not form_data['title']:
        return {"error": "Formda analiz edilecek öğe bulunamadı."}
    return form_data


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang=\"tr\">
<head>
    <meta charset=\"UTF-8\">
    <title>Google Form Klonlayıcı</title>
    <meta name=\"viewport\" content=\"width=device-width,initial-scale=1.0\">
    <style>
        body { font-family: Arial, sans-serif; background: #f4f7fa; margin: 0; padding: 2rem; display: flex; justify-content: center; }
        .container { max-width: 760px; width: 100%; background: #fff; padding: 2rem 2.2rem; border-radius: 12px; box-shadow: 0 10px 25px rgba(0,0,0,.08); }
        h1 { text-align: center; margin: 0 0 1rem; }
        .form-group { margin-bottom: 1.6rem; padding: 1.2rem; border: 1px solid #dbe2e9; border-radius: 8px; background: #fdfdff; }
        .question-label { display: block; font-weight: 600; margin-bottom: .9rem; }
        .required-star { color: #e74c3c; margin-left: 4px; }
        input[type=text], input[type=email], textarea, select, input[type=date], input[type=time] { width: 100%; padding: .8rem 1rem; border: 1px solid #dbe2e9; border-radius: 6px; box-sizing: border-box; font-size: 1rem; }
        textarea { min-height: 100px; resize: vertical; }
        input:focus, textarea:focus, select:focus { outline: none; border-color: #4a80ff; box-shadow: 0 0 0 3px rgba(74,128,255,.2); }
        .radio-group, .checkbox-group { display: flex; flex-direction: column; gap: .6rem; }
        .radio-group label, .checkbox-group label { display: flex; align-items: center; gap: .6rem; cursor: pointer; padding: .4rem .5rem; border-radius: 6px; }
        .radio-group label:hover, .checkbox-group label:hover { background: #f0f4ff; }
        input[type=radio], input[type=checkbox] { width: 1.1rem; height: 1.1rem; accent-color: #4a80ff; }
        .btn { background: #4a80ff; color: #fff; padding: .9rem 1.4rem; border: none; width: 100%; border-radius: 6px; font-size: 1.05rem; font-weight: 600; cursor: pointer; }
        .btn:hover { background: #3c6de0; }
        .error-message { background: #e74c3c; color: #fff; padding: 1rem; border-radius: 6px; text-align: center; }
        .grid-table { width: 100%; border-collapse: collapse; margin-top: .5rem; }
        .grid-table th, .grid-table td { border: 1px solid #dbe2e9; padding: .6rem; text-align: center; font-size: .9rem; }
        .grid-table th { background: #f8f9fa; }
        .grid-table td:first-child { text-align: left; font-weight: 600; }
        .rating-group { display: flex; flex-direction: row-reverse; justify-content: center; gap: 5px; }
        .rating-group input { display: none; }
        .rating-group label { font-size: 2rem; color: #ccc; cursor: pointer; }
        .rating-group input:checked ~ label,
        .rating-group label:hover,
        .rating-group label:hover ~ label { color: #f39c12; }
        .other-option-label { align-items: center; }
        .other-option-input { flex-grow: 1; padding: .4rem .6rem; }
        .option-image { max-width: 80px; height: auto; margin-right: 10px; vertical-align: middle; border-radius: 4px; }
        /* Yeni öğeler için stil */
        .form-section-header { background:#e0edfe; padding:1.5rem; margin-top:2rem; border-color:#c0dfff; border-radius: 8px; }
        .form-section-header h2 { margin-top:0; color:#3a5a9a; }
        .form-section-header p { white-space:pre-wrap; color:#555; line-height:1.5; }
        .form-image-block { padding:1rem; text-align:center; background:#f0f7ff; border-color:#d0e7ff; border-radius: 8px; }
        .form-image-block p { font-weight:bold; color:#3a5a9a; }
        .warning-message { background: #ffc107; color: #333; padding: 0.8rem; border-radius: 6px; text-align: center; margin-top: 0.5rem; }
    </style>
</head>
<body>
<div class=\"container\">
    <h1>Google Form Klonlayıcı</h1>
    <form method=\"post\" action=\"/\">
        <div class=\"form-group\" style=\"padding:0.8rem;\">
            <input type=\"text\" name=\"url\" placeholder=\"https://docs.google.com/forms/d/e/...\" required>
            <button type=\"submit\" class=\"btn\" style=\"margin-top:.8rem;\">Formu Oluştur</button>
        </div>
    </form>
    {% if error %}<div class=\"error-message\">{{ error }}</div>{% endif %}

    {% if form_data %}
        <h2 style=\"text-align:center;margin-top:1.5rem;\">{{ form_data.title | safe }}</h2>
        {% if form_data.description %}<p style=\"white-space:pre-wrap;color:#555;line-height:1.5;\">{{ form_data.description | safe }}</p>{% endif %}

        <form method=\"post\" action=\"/submit\">
        {% for item in form_data.items %}
            {% if item.type == 'Question' %}
            <div class=\"form-group\">
                <label class=\"question-label\">{{ item.text | safe }} {% if item.required %}<span class=\"required-star\">*</span>{% endif %}</label>
                {% set qid = item.entry_id if item.entry_id else (item.rows[0].entry_id if item.rows|length > 0 else '') %}

                {# E-posta alanı özel olarak ele alınır #}
                {% if item.original_type == 'E-posta' %}
                <input type=\"email\" name=\"{{ item.entry_id }}\" {% if item.required %}required{% endif %} pattern=\".+@gmail\\.com\">
                {% elif item.type == 'Kısa Yanıt' %}
                <input type=\"text\" name=\"{{ item.entry_id }}\" {% if item.required %}required{% endif %}>
                {% elif item.type == 'Paragraf' %}
                <textarea name=\"{{ item.entry_id }}\" {% if item.required %}required{% endif %}></textarea>
                {% elif item.type == 'Çoktan Seçmeli' %}
                <div class=\"radio-group\">
                {% if item.options is defined and item.options is not none and item.options is iterable %}
                    {% for opt in item.options %}
                    <label>
                        <input type=\"radio\" name=\"{{ item.entry_id }}\" value=\"{{ opt.text | safe }}\" {% if item.required %}required{% endif %}>
                        {% if opt.image_url %}<img src=\"{{ opt.image_url }}\" class=\"option-image\">{% endif %}
                        <span>{{ opt.text | safe }}</span>
                    </label>
                    {% endfor %}
                {% else %}
                    <div class=\"warning-message\">Uyarı: Bu çoktan seçmeli soru için seçenekler beklenildiği gibi değil. Lütfen formu kontrol edin.</div>
                {% endif %}
                {% if item.has_other %}
                <label class=\"other-option-label\">
                    <input type=\"radio\" name=\"{{ item.entry_id }}\" value=\"__other_option__\">
                    <span>Diğer:</span>
                    <input type=\"text\" class=\"other-option-input\" name=\"{{ item.entry_id }}.other_option_response\">
                </label>
                {% endif %}
                </div>
                {% elif item.type == 'Onay Kutuları' %}
                <div class=\"checkbox-group\">
                {% if item.options is defined and item.options is not none and item.options is iterable %}
                    {% for opt in item.options %}
                    <label>
                        <input type=\"checkbox\" name=\"{{ item.entry_id }}\" value=\"{{ opt.text | safe }}\">
                        {% if opt.image_url %}<img src=\"{{ opt.image_url }}\" class=\"option-image\">{% endif %}
                        <span>{{ opt.text | safe }}</span>
                    </label>
                    {% endfor %}
                {% else %}
                    <div class=\"warning-message\">Uyarı: Bu onay kutulu soru için seçenekler beklenildiği gibi değil. Lütfen formu kontrol edin.</div>
                {% endif %}
                {% if item.has_other %}
                <label class=\"other-option-label\">
                    <input type=\"checkbox\" name=\"{{ item.entry_id }}\" value=\"__other_option__\">
                    <span>Diğer:</span>
                    <input type=\"text\" class=\"other-option-input\" name=\"{{ item.entry_id }}.other_option_response\">
                </label>{% endif %}
                </div>
                {% elif item.type == 'Açılır Liste' %}
                {% if item.options is defined and item.options is not none and item.options is iterable %}
                <select name=\"{{ item.entry_id }}\" {% if item.required %}required{% endif %}>
                    <option value=\"\" disabled selected>Seçin...</option>
                    {% for opt in item.options %}<option value=\"{{ opt.text | safe }}\">{{ opt.text | safe }}</option>{% endfor %}
                </select>
                {% else %}
                    <div class=\"warning-message\">Uyarı: Bu açılır liste soru için seçenekler beklenildiği gibi değil. Lütfen formu kontrol edin.</div>
                {% endif %}
                {% elif item.type == 'Doğrusal Ölçek' %}
                <div class=\"radio-group\" style=\"flex-direction:row;justify-content:space-around;align-items:center;\">
                    <span>{{ item.labels[0] | safe }}</span>
                {% if item.options is defined and item.options is not none and item.options is iterable %}
                    {% for opt in item.options %}
                    <label style=\"flex-direction:column;\"><span>{{ opt.text | safe }}</span>
                    <input type=\"radio\" name=\"{{ item.entry_id }}\" value=\"{{ opt.text | safe }}\" {% if item.required %}required{% endif %}>
                    </label>
                    {% endfor %}
                {% else %}
                    <div class=\"warning-message\">Uyarı: Bu doğrusal ölçek soru için seçenekler beklenildiği gibi değil. Lütfen formu kontrol edin.</div>
                {% endif %}
                    <span>{{ item.labels[1] | safe }}</span>
                </div>
                {% elif item.type == 'Derecelendirme' %}
                <div class=\"rating-group\">
                {% if item.options is defined and item.options is not none and item.options is iterable %}
                    {% for opt in item.options | reverse %}
                    <input type=\"radio\" id=\"star{{ opt.text | safe }}-{{ item.entry_id }}\" name=\"{{ item.entry_id }}\" value=\"{{ opt.text | safe }}\" {% if item.required %}required{% endif %}>
                    <label for=\"star{{ opt.text | safe }}-{{ item.entry_id }}\">★</label>
                    {% endfor %}
                {% else %}
                    <div class=\"warning-message\">Uyarı: Bu derecelendirme soru için seçenekler beklenildiği gibi değil. Lütfen formu kontrol edin.</div>
                {% endif %}
                </div>
                {% elif item.type == 'Tarih' %}
                <input type=\"date\" name=\"{{ item.entry_id }}\" {% if item.required %}required{% endif %}>
                {% elif item.type == 'Saat' %}
                <input type=\"time\" name=\"{{ item.entry_id }}\" {% if item.required %}required{% endif %}>
                {% elif item.type in ['Çoktan Seçmeli Tablo','Onay Kutusu Tablosu'] %}
                <table class=\"grid-table\">
                    <thead>
                        <tr>
                            <th></th>
                            {% for col in item.cols %}<th>{{ col }}</th>{% endfor %}
                        </tr>
                    </thead>
                    <tbody>
                        {% for row in item.rows %}
                        <tr>
                            <td>{{ row.text | safe }}</td>
                            {% for col in item.cols %}
                            <td><input type=\"{{ 'checkbox' if 'Onay' in item.type else 'radio' }}\" name=\"{{ row.entry_id }}\" value=\"{{ col }}\" {% if item.required and 'Onay' not in item.type %}required{% endif %}></td>
                            {% endfor %}
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
                {% endif %}
            </div>
            {% elif item.type == 'Section' %}
            <div class=\"form-group form-section-header\">
                <h2>{{ item.title | safe }}</h2>
                {% if item.description %}<p>{{ item.description | safe }}</p>{% endif %}
                {% if item.image_url %}<div style=\"text-align:center; margin-top:1rem;\"><img src=\"{{ item.image_url }}\" style=\"max-width:100%; height:auto; border-radius:8px;\"></div>{% endif %}
            </div>
            {% elif item.type == 'Image' %}
            <div class=\"form-group form-image-block\">
                {% if item.title %}<p>{{ item.title | safe }}</p>{% endif %}
                <img src=\"{{ item.image_url }}\" style=\"max-width:100%; height:auto; border-radius:8px;\">
            </div>
            {% endif %}
        {% endfor %}
        <button type=\"submit\" class=\"btn\">Gönder ve Excel Olarak İndir</button>
        </form>
    {% endif %}
</div>
</body>
</html>
"""

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        url = request.form.get('url', '').strip()
        if not url or "docs.google.com/forms" not in url:
            return render_template_string(HTML_TEMPLATE, error="Geçerli bir Google Form URL'si girin.")
        
        form_data = analyze_google_form(url)
        if "error" in form_data:
            return render_template_string(HTML_TEMPLATE, error=form_data["error"])
        
        session['form_structure'] = form_data
        return render_template_string(HTML_TEMPLATE, form_data=form_data)
    
    return render_template_string(HTML_TEMPLATE)

@app.route('/submit', methods=['POST'])
def submit():
    form_structure = session.get('form_structure')
    if not form_structure or 'items' not in form_structure:
        return "Hata: Form yapısı bulunamadı veya oturum zaman aşımına uğradı.", 400

    user_answers = request.form
    results = []

    for item in form_structure['items']:  # Tüm form öğeleri arasında döngü yap
        if item.get('type') != 'Question':  # Yalnızca soruları cevaplar için işle
            continue

        q_text = item['text']
        q_type = item.get('type') # Bu, dahili olarak ayrıştırılmış tiptir ('Kısa Yanıt' gibi)
        original_q_type = item.get('original_type', q_type)  # Özel E-posta alanı için

        # E-posta alanını özel olarak ele al
        if original_q_type == 'E-posta':
            answer_str = user_answers.get(item['entry_id'], "Boş Bırakıldı")
            results.append({"Soru": q_text, "Soru Tipi": original_q_type, "Cevap": answer_str})
            continue

        # Matris tablo (Çoktan Seçmeli Tablo veya Onay Kutusu Tablosu)
        if 'Tablo' in q_type:
            for row in item['rows']:
                rid = row['entry_id']
                row_label = f"{q_text} [{row['text']}]"
                if 'Onay' in q_type:  # Onay kutusu tablosu
                    answers = user_answers.getlist(rid)
                    val = ', '.join(answers) if answers else "Boş Bırakıldı"
                else:  # Çoktan seçmeli tablo (radio buton)
                    val = user_answers.get(rid, "Boş Bırakıldı")
                results.append({"Soru": row_label, "Soru Tipi": q_type, "Cevap": val})
            continue

        entry = item.get('entry_id')
        answer_str = "Boş Bırakıldı"

        if q_type == 'Onay Kutuları':
            answers = user_answers.getlist(entry)
            final = []
            other_txt_key = f"{entry}.other_option_response"
            other_txt_value = user_answers.get(other_txt_key, "").strip()

            # "Diğer" onay kutusu seçiliyse VEYA "Diğer" metin alanında içerik varsa
            if "__other_option__" in answers or other_txt_value:
                if other_txt_value:
                    final.append(f"Diğer: {other_txt_value}")
                else:
                    final.append("Diğer (belirtilmemiş)")  # Kutu işaretli ama metin boşsa
            
            # Diğer seçili seçenekleri ekle, "__other_option__" değerini listeden hariç tut
            for ans in answers:
                if ans != "__other_option__":
                    final.append(ans)
            
            answer_str = ', '.join(final) if final else "Boş Bırakıldı"

        elif q_type == 'Çoktan Seçmeli':
            ans = user_answers.get(entry)
            other_txt_key = f"{entry}.other_option_response"
            other_txt_value = user_answers.get(other_txt_key, "").strip()
            
            # "Diğer" radio butonu seçiliyse VEYA hiçbir radio seçili değilken "Diğer" metin alanında içerik varsa
            if ans == "__other_option__" or (ans is None and other_txt_value):
                answer_str = f"Diğer: {other_txt_value}" if other_txt_value else "Diğer (belirtilmemiş)"
            elif ans:
                answer_str = ans
            else:
                answer_str = "Boş Bırakıldı"

        else:
            answer_str = user_answers.get(entry, "Boş Bırakıldı")

        results.append({"Soru": q_text, "Soru Tipi": q_type, "Cevap": answer_str})

    df = pd.DataFrame(results)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        sheet = 'Form Cevaplari'
        df.to_excel(writer, index=False, sheet_name=sheet)
        ws = writer.sheets[sheet]
        for i, col in enumerate(df.columns):
            max_len = max([len(str(x)) for x in df[col].tolist()] + [len(col)])
            ws.column_dimensions[chr(65 + i)].width = min(max_len + 2, 60)
    output.seek(0)
    session.pop('form_structure', None)  # Form yapısını oturumdan temizle
    return send_file(output,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True,
                     download_name='form_cevaplari.xlsx')

if __name__ == '__main__':
    # Lokal geliştirme için. Production'da: gunicorn app:app
    app.run(host='0.0.0.0', port=5000, debug=True)
