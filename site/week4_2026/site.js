(function(){
  var tbody=document.querySelector('#list tbody'); if(!tbody) return;
  var rows=[].slice.call(tbody.rows), key='hit', dir=-1, filt='all';
  function render(){
    rows.sort(function(a,b){
      var x=a.dataset[key], y=b.dataset[key];
      if(key==='ko') return x<y?-dir:x>y?dir:0;
      return (parseFloat(x)-parseFloat(y))*dir;
    });
    var n=0;
    rows.forEach(function(r){ tbody.appendChild(r); var show=filt==='all'||r.dataset.market===filt;
      r.hidden=!show; if(show){ r.cells[0].textContent=++n; } });
    document.querySelectorAll('#list th[data-sort]').forEach(function(th){
      if(th.dataset.sort===key) th.setAttribute('aria-sort', dir<0?'descending':'ascending'); else th.removeAttribute('aria-sort'); });
  }
  document.querySelectorAll('#list th[data-sort] button').forEach(function(b){
    b.addEventListener('click',function(){ var k=b.parentNode.dataset.sort;
      if(k===key) dir=-dir; else { key=k; dir=(k==='ko')?1:-1; } render(); });
  });
  document.querySelectorAll('.filters button').forEach(function(b){
    b.addEventListener('click',function(){ filt=b.dataset.f;
      document.querySelectorAll('.filters button').forEach(function(o){o.setAttribute('aria-pressed', o===b?'true':'false');});
      render(); });
  });
  render();
})();
