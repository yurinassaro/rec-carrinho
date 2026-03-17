"""Middleware que injeta botão CRM no admin Django."""


class CRMButtonMiddleware:
    """Injeta botão CRM no header do Django Admin."""

    CRM_SCRIPT = b"""
<script>
(function(){
  if(document.getElementById('crm-nav-btn'))return;
  var ut=document.getElementById('user-tools');
  if(!ut)return;
  var a=document.createElement('a');
  a.id='crm-nav-btn';
  a.href='/crm/';
  a.textContent='\\u{1F4CA} CRM';
  a.style.cssText='background:linear-gradient(135deg,#6366f1,#818cf8);color:#fff!important;padding:6px 18px;border-radius:6px;text-decoration:none;font-weight:700;font-size:12px;margin-right:10px;display:inline-block;letter-spacing:.5px;vertical-align:middle;transition:all .2s;';
  a.onmouseenter=function(){a.style.background='linear-gradient(135deg,#818cf8,#a78bfa)';a.style.boxShadow='0 4px 12px rgba(99,102,241,0.4)';};
  a.onmouseleave=function(){a.style.background='linear-gradient(135deg,#6366f1,#818cf8)';a.style.boxShadow='none';};
  ut.insertBefore(a,ut.firstChild);
})();
</script>
"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if (
            request.path.startswith('/admin/')
            and hasattr(response, 'content')
            and response.get('Content-Type', '').startswith('text/html')
        ):
            content = response.content
            closing = b'</body>'
            if closing in content:
                response.content = content.replace(closing, self.CRM_SCRIPT + closing)
                if 'Content-Length' in response:
                    response['Content-Length'] = len(response.content)

        return response
