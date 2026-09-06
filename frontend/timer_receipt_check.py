"""Deterministic browser regression: timer isolation and scoped answer receipts.
Run against a local frontend on port 3000; HTTP and game sockets are mocked.
"""
import json
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright, expect

INIT = r'''(() => {
  localStorage.setItem('party-quiz-player', JSON.stringify({player_id:'guest',username:'Guest',session_id:'test'}));
  const NativeSocket = window.WebSocket;
  class GameSocket {
    static OPEN = 1; static CONNECTING = 0; static CLOSED = 3;
    constructor(url) {
      if (!url.includes('/ws/rooms/')) return new NativeSocket(url);
      this.readyState = 0; window.gameSocket = this;
      setTimeout(() => {this.readyState=1; this.onopen?.({});}, 20);
    }
    send(text) { const message=JSON.parse(text); window.sent.push(message); }
    close() { this.readyState=3; this.onclose?.({code:1000}); }
  }
  window.sent=[]; window.WebSocket=GameSocket;
  window.emit = (type,payload) => window.gameSocket.onmessage({data:JSON.stringify({type,payload})});
  window.roomRenders=0; window.timerRenders=0;
  window.__REACT_DEVTOOLS_GLOBAL_HOOK__ = {
    supportsFiber:true, renderers:new Map(), inject:()=>1, onCommitFiberUnmount:()=>{},
    onCommitFiberRoot:(_id,root)=>{
      function visit(f) {
        if (!f) return;
        if (f.type?.name === 'RoomPage' && (f.flags & 1)) window.roomRenders++;
        if (f.type?.name === 'RoomTimer' && (f.flags & 1)) window.timerRenders++;
        visit(f.child); visit(f.sibling);
      }
      visit(root.current);
    }
  };
})();'''

def snapshot():
    now=datetime.now(timezone.utc)
    return {'turn_id':'game-1:0','title':None,'status':'QUESTION','owner_id':'owner',
      'players':[{'id':i,'username':i,'score':1,'ready':True,'connected':True} for i in ['owner','guest']],
      'current_question_index':0,'question_count':2,'round_count':1,'current_round':1,
      'current_parent_id':'owner','answered':1,
      'settings':{'game_name':'Test','max_players':12,'selection_duration':15,'question_duration':20,'result_duration':5},
      'clock':{'revision':1,'phase':'QUESTION','server_time':now.isoformat(),'running':True,'started_at':now.isoformat(),'ends_at':(now+timedelta(seconds=20)).isoformat(),'duration_ms':20000,'remaining_ms':20000},
      'question':{'id':'q1','title':'このボタン、押す？','option_a':'押す','option_b':'押さない'}}

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    for width,height in [(390,844),(375,667)]:
        context=browser.new_context(viewport={'width':width,'height':height})
        context.add_init_script(INIT)
        state=snapshot()
        restored={'draft_choice':None,'confirmed_choice':None}
        context.route('**/api/rooms/TEST/join',lambda route:route.fulfill(headers={'Access-Control-Allow-Origin':'*','Access-Control-Allow-Headers':'content-type','Access-Control-Allow-Methods':'POST, OPTIONS'},json={'player_id':'guest','session_id':'test','room':state,**restored}))
        context.route('**/api/players/*/avatar*',lambda route:route.fulfill(status=204))
        page=context.new_page()
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto('http://localhost:3000/room/TEST',wait_until='networkidle')
        try:
            expect(page.locator('.question-card')).to_be_visible()
        except Exception:
            print('browser errors:', errors)
            print(page.locator('body').inner_text())
            raise
        page.wait_for_function('window.gameSocket?.readyState === 1 && window.timerRenders > 0')
        counts=page.evaluate('({room:roomRenders,timer:timerRenders})')
        before=page.locator('[role=timer]').inner_text()
        page.wait_for_timeout(1200)
        after=page.evaluate('({room:roomRenders,timer:timerRenders})')
        assert after['room']==counts['room'], (counts,after)
        assert after['timer']>counts['timer']+10, (counts,after)
        assert page.locator('[role=timer]').inner_text()!=before
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.locator('.choice.a').click()
        page.locator('.confirm-answer').click()
        request=page.evaluate("sent.filter(m=>m.type==='answer').at(-1).payload")
        assert request['turn_id']==state['turn_id'] and request['request_id']
        # Another request's response must not mark this request complete.
        page.evaluate("p=>emit('answer_saved',p)",{**request,'request_id':'wrong'})
        assert page.locator('.confirmed-choice').count()==0
        page.locator('.choice.b').click()
        page.evaluate("p=>emit('answer_saved',p)",request)
        expect(page.locator('.choice.a')).to_have_class('choice a confirmed-choice')
        expect(page.locator('.choice.b')).to_have_class('choice b selected-choice')
        page.locator('.confirm-answer').click()
        second=page.evaluate("sent.filter(m=>m.type==='answer').at(-1).payload")
        page.evaluate("p=>emit('answer_saved',p)",request)
        expect(page.locator('.confirm-answer')).to_be_disabled()
        page.evaluate("p=>emit('error',p)",{**request,'operation':'answer','message':'INVALID_ANSWER'})
        expect(page.locator('.confirm-answer')).to_be_disabled()
        page.evaluate("p=>emit('answer_saved',p)",second)
        expect(page.locator('.choice.b')).to_have_class('choice b selected-choice confirmed-choice')
        # Same question reused in another game/turn must clear confirmation.
        state['turn_id']='game-2:0';state['clock']['revision']=2
        page.evaluate("s=>emit('game_state',s)",state)
        expect(page.locator('.confirmed-choice')).to_have_count(0)
        page.evaluate("p=>emit('answer_saved',p)",second)
        expect(page.locator('.confirmed-choice')).to_have_count(0)
        page.evaluate("p=>emit('answer_saved',p)",{'turn_id':state['turn_id'],'question_id':'wrong','choice':'A','automatic':True})
        expect(page.locator('.confirmed-choice')).to_have_count(0)
        page.evaluate("p=>emit('answer_saved',p)",{'turn_id':state['turn_id'],'question_id':'q1','choice':'B','automatic':True,'request_id':None})
        expect(page.locator('.choice.b')).to_have_class('choice b selected-choice confirmed-choice')
        # A reconnect restores durable answers and clears any pending confirmation.
        page.locator('.choice.a').click()
        page.locator('.confirm-answer').click()
        restored.update({'draft_choice':'A','confirmed_choice':'B'})
        page.evaluate('gameSocket.close()')
        page.wait_for_function("window.sent.filter(m=>m.type==='time_sync').length >= 2")
        expect(page.locator('.choice.a')).to_have_class('choice a selected-choice')
        expect(page.locator('.choice.b')).to_have_class('choice b confirmed-choice')
        expect(page.locator('.confirm-answer')).to_be_enabled()
        # A frozen clock retains its authoritative remaining time.
        state['clock'].update({'running':False,'remaining_ms':5000,'revision':3,'ends_at':None})
        page.evaluate("s=>emit('game_state',s)",state)
        expect(page.locator('[role=timer]')).to_have_text('5秒')
        page.wait_for_timeout(100)
        frozen=page.evaluate('timerRenders')
        page.wait_for_timeout(250)
        assert page.evaluate('timerRenders')==frozen
        # Expired clocks clamp to zero and await the server's phase transition.
        state['clock'].update({'running':True,'revision':4,'ends_at':'2000-01-01T00:00:00Z'})
        page.evaluate("s=>emit('game_state',s)",state)
        expect(page.locator('[role=timer]')).to_have_text('0秒')
        expect(page.locator('.question-card')).to_be_visible()
        # Pause freezes the timer and stops scheduled commits.
        state['status']='PAUSED';state['clock'].update({'running':False,'remaining_ms':5000,'revision':5,'phase':'PAUSED','ends_at':None})
        page.evaluate("s=>emit('game_state',s)",state)
        expect(page.locator('.paused-card')).to_be_visible()
        assert not errors,errors
        print(f'{width}x{height}: timer ticks {after["timer"]-counts["timer"]}, room renders 0; scoped receipts passed')
        context.close()
    browser.close()
