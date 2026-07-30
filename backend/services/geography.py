"""Map phone numbers to countries and Brazilian states.

Data source: customers.whatsapp field (E.164 digits without +).

Country resolution:
- Uses DDI prefix (1 = US/CA, 34 = ES, 44 = UK, 351 = PT, 55 = BR, etc.)
- Longest-prefix match wins (351 beats 3)

Brazilian state resolution:
- +55 followed by 2-digit DDD (11 = SP, 21 = RJ, 31 = MG, ...)
- Returns state code + full name + capital city approx coords
"""
from typing import Optional

# Country data: DDI → (iso_alpha2, name, lat, lng, flag_emoji)
# Focus on countries commonly seen in Brazilian IPTV/P2P client bases.
# Fallback: unknown DDIs fall into "Outros" bucket with global center coords.
COUNTRIES = {
    # BR — Brazil (primary market)
    "55": ("BR", "Brasil", -14.235, -51.9253, "🇧🇷"),
    # Americas
    "1":  ("US", "Estados Unidos / Canadá", 39.8283, -98.5795, "🇺🇸"),
    "52": ("MX", "México", 23.6345, -102.5528, "🇲🇽"),
    "54": ("AR", "Argentina", -38.4161, -63.6167, "🇦🇷"),
    "56": ("CL", "Chile", -35.6751, -71.5430, "🇨🇱"),
    "57": ("CO", "Colômbia", 4.5709, -74.2973, "🇨🇴"),
    "58": ("VE", "Venezuela", 6.4238, -66.5897, "🇻🇪"),
    "51": ("PE", "Peru", -9.19, -75.0152, "🇵🇪"),
    "593": ("EC", "Equador", -1.8312, -78.1834, "🇪🇨"),
    "595": ("PY", "Paraguai", -23.4425, -58.4438, "🇵🇾"),
    "598": ("UY", "Uruguai", -32.5228, -55.7658, "🇺🇾"),
    "591": ("BO", "Bolívia", -16.2902, -63.5887, "🇧🇴"),
    # Europe
    "351": ("PT", "Portugal", 39.3999, -8.2245, "🇵🇹"),
    "34": ("ES", "Espanha", 40.4637, -3.7492, "🇪🇸"),
    "33": ("FR", "França", 46.2276, 2.2137, "🇫🇷"),
    "39": ("IT", "Itália", 41.8719, 12.5674, "🇮🇹"),
    "44": ("GB", "Reino Unido", 55.3781, -3.4360, "🇬🇧"),
    "49": ("DE", "Alemanha", 51.1657, 10.4515, "🇩🇪"),
    "353": ("IE", "Irlanda", 53.1424, -7.6921, "🇮🇪"),
    "31": ("NL", "Holanda", 52.1326, 5.2913, "🇳🇱"),
    "32": ("BE", "Bélgica", 50.5039, 4.4699, "🇧🇪"),
    "41": ("CH", "Suíça", 46.8182, 8.2275, "🇨🇭"),
    "43": ("AT", "Áustria", 47.5162, 14.5501, "🇦🇹"),
    "45": ("DK", "Dinamarca", 56.2639, 9.5018, "🇩🇰"),
    "46": ("SE", "Suécia", 60.1282, 18.6435, "🇸🇪"),
    "47": ("NO", "Noruega", 60.4720, 8.4689, "🇳🇴"),
    # Africa
    "27": ("ZA", "África do Sul", -30.5595, 22.9375, "🇿🇦"),
    "244": ("AO", "Angola", -11.2027, 17.8739, "🇦🇴"),
    "258": ("MZ", "Moçambique", -18.6657, 35.5296, "🇲🇿"),
    # Asia/Oceania
    "61": ("AU", "Austrália", -25.2744, 133.7751, "🇦🇺"),
    "81": ("JP", "Japão", 36.2048, 138.2529, "🇯🇵"),
    "86": ("CN", "China", 35.8617, 104.1954, "🇨🇳"),
    "91": ("IN", "Índia", 20.5937, 78.9629, "🇮🇳"),
}


# Brazilian DDD → (state code, state name, lat, lng of capital area)
BR_DDD = {
    "11": ("SP", "São Paulo (Capital)", -23.5505, -46.6333),
    "12": ("SP", "São José dos Campos", -23.2237, -45.9009),
    "13": ("SP", "Santos", -23.9608, -46.3336),
    "14": ("SP", "Bauru", -22.3145, -49.0603),
    "15": ("SP", "Sorocaba", -23.5015, -47.4526),
    "16": ("SP", "Ribeirão Preto", -21.1775, -47.8103),
    "17": ("SP", "São José do Rio Preto", -20.8114, -49.3767),
    "18": ("SP", "Presidente Prudente", -22.1256, -51.3889),
    "19": ("SP", "Campinas", -22.9099, -47.0626),
    "21": ("RJ", "Rio de Janeiro (Capital)", -22.9068, -43.1729),
    "22": ("RJ", "Campos dos Goytacazes", -21.7642, -41.3181),
    "24": ("RJ", "Petrópolis / Volta Redonda", -22.5117, -43.1783),
    "27": ("ES", "Espírito Santo (Vitória)", -20.3155, -40.3128),
    "28": ("ES", "Cachoeiro de Itapemirim", -20.8489, -41.1128),
    "31": ("MG", "Belo Horizonte", -19.9167, -43.9345),
    "32": ("MG", "Juiz de Fora", -21.7595, -43.3496),
    "33": ("MG", "Governador Valadares", -18.8511, -41.9494),
    "34": ("MG", "Uberlândia", -18.9186, -48.2772),
    "35": ("MG", "Poços de Caldas / Varginha", -21.7867, -46.5647),
    "37": ("MG", "Divinópolis", -20.1444, -44.8912),
    "38": ("MG", "Montes Claros", -16.7286, -43.8583),
    "41": ("PR", "Curitiba", -25.4284, -49.2733),
    "42": ("PR", "Ponta Grossa", -25.0916, -50.1626),
    "43": ("PR", "Londrina", -23.3103, -51.1628),
    "44": ("PR", "Maringá", -23.4205, -51.9331),
    "45": ("PR", "Cascavel / Foz do Iguaçu", -25.5478, -54.5882),
    "46": ("PR", "Pato Branco", -26.2296, -52.6706),
    "47": ("SC", "Joinville / Blumenau", -26.9187, -49.0661),
    "48": ("SC", "Florianópolis", -27.5954, -48.5480),
    "49": ("SC", "Chapecó", -27.1006, -52.6156),
    "51": ("RS", "Porto Alegre", -30.0346, -51.2177),
    "53": ("RS", "Pelotas", -31.7654, -52.3376),
    "54": ("RS", "Caxias do Sul", -29.1685, -51.1793),
    "55": ("RS", "Santa Maria", -29.6842, -53.8069),
    "61": ("DF", "Brasília / DF", -15.8267, -47.9218),
    "62": ("GO", "Goiânia", -16.6869, -49.2648),
    "63": ("TO", "Tocantins (Palmas)", -10.1689, -48.3317),
    "64": ("GO", "Rio Verde", -17.7975, -50.9264),
    "65": ("MT", "Cuiabá", -15.5989, -56.0949),
    "66": ("MT", "Rondonópolis", -16.4706, -54.6353),
    "67": ("MS", "Campo Grande", -20.4697, -54.6201),
    "68": ("AC", "Acre (Rio Branco)", -8.7619, -70.5519),
    "69": ("RO", "Rondônia (Porto Velho)", -11.5057, -63.5806),
    "71": ("BA", "Salvador", -12.9714, -38.5014),
    "73": ("BA", "Ilhéus / Itabuna", -14.7935, -39.0463),
    "74": ("BA", "Juazeiro", -9.4116, -40.5013),
    "75": ("BA", "Feira de Santana", -12.2664, -38.9663),
    "77": ("BA", "Vitória da Conquista", -14.8619, -40.8444),
    "79": ("SE", "Sergipe (Aracaju)", -10.9472, -37.0731),
    "81": ("PE", "Recife", -8.0476, -34.8770),
    "82": ("AL", "Alagoas (Maceió)", -9.6658, -35.7353),
    "83": ("PB", "Paraíba (João Pessoa)", -7.1195, -34.8450),
    "84": ("RN", "Rio G. do Norte (Natal)", -5.7945, -35.2110),
    "85": ("CE", "Fortaleza", -3.7319, -38.5267),
    "86": ("PI", "Piauí (Teresina)", -5.0919, -42.8034),
    "87": ("PE", "Petrolina / interior PE", -9.3891, -40.5027),
    "88": ("CE", "Juazeiro do Norte", -7.2136, -39.3178),
    "89": ("PI", "Picos / interior PI", -7.0765, -41.4664),
    "91": ("PA", "Belém", -1.4558, -48.4902),
    "92": ("AM", "Manaus", -3.1190, -60.0217),
    "93": ("PA", "Santarém", -2.4437, -54.7085),
    "94": ("PA", "Marabá", -5.3689, -49.1174),
    "95": ("RR", "Roraima (Boa Vista)", 2.8235, -60.6758),
    "96": ("AP", "Amapá (Macapá)", 0.0349, -51.0694),
    "97": ("AM", "Interior do Amazonas", -3.8447, -66.2394),
    "98": ("MA", "São Luís", -2.5307, -44.3068),
    "99": ("MA", "Imperatriz", -5.5252, -47.4818),
}


def resolve_country(phone_digits: str) -> Optional[dict]:
    """Longest-prefix DDI match. Returns dict or None if phone is bogus."""
    if not phone_digits or not phone_digits.isdigit():
        return None
    # Try 3-digit, 2-digit, 1-digit prefixes in that order.
    for length in (3, 2, 1):
        prefix = phone_digits[:length]
        entry = COUNTRIES.get(prefix)
        if entry:
            iso, name, lat, lng, flag = entry
            return {
                "code": iso, "name": name, "lat": lat, "lng": lng,
                "flag": flag, "ddi": prefix,
            }
    return None


def resolve_br_state(phone_digits: str) -> Optional[dict]:
    """For BR numbers (starts with 55), return the state from DDD."""
    if not phone_digits or not phone_digits.startswith("55") or len(phone_digits) < 4:
        return None
    ddd = phone_digits[2:4]
    entry = BR_DDD.get(ddd)
    if not entry:
        return None
    uf, region_name, lat, lng = entry
    return {
        "ddd": ddd, "uf": uf, "region": region_name,
        "lat": lat, "lng": lng,
    }
