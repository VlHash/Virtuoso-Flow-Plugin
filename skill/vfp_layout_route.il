;; =====================================================================
;; vfp_layout_route.il — layout routing: a pluggable INTERFACE + a BASIC
;;                       built-in connectivity router (VFP layout)
;; ---------------------------------------------------------------------
;; Scope (deliberately small): VFP owns the routing *interface* and a
;; *basic* reference router, NOT an optimized one. Cadence's batch router
;; (Chip Assembly) is digital-only and the XL wire tool is interactive, so
;; VFP needs its own hook so an external optimizer can drive routing — but
;; the optimized routing/placement is a consuming layer's job (a closed
;; engine), not this repo. So:
;;
;;   - vfpRegisterRouter(name fn)  -- register a router backend
;;   - vfpLayoutRoute(cv ...)      -- run the ACTIVE backend (default "basic")
;;   - the built-in "basic" backend: a 2-layer (M1/M2) Lee maze router that
;;     connects each net's terminals avoiding device obstacles + other nets
;;     (different layers don't short except at vias). Connectivity-correct,
;;     best-effort DRC (grid pitch ~ DRC pitch). NOT optimized.
;;
;; A consuming engine registers a better backend (vfpRegisterRouter "opt" fn)
;; and selects it via VFP_ROUTER / vfpStateSet('router ...). The basic router
;; is the standalone fallback so VFP routes on its own.
;;
;; Loaded after vfp_utils / vfp_rpc_client / vfp_layout (connectivity).
;; =====================================================================

;; ---- grid model: struct = (nc nr occ x0 y0 pitch) -------------------
;; layers 0=M1, 1=M2.  occ[idx] = netName | 'obs | nil(free)
defun( vfpRGmake (nc nr x0 y0 pitch) list(nc nr makeTable('occ nil) x0 y0 pitch) )
defun( vfpRGnc (g) nth(0 g) )
defun( vfpRGnr (g) nth(1 g) )
defun( vfpRGocc (g) nth(2 g) )
defun( vfpRGx0 (g) nth(3 g) )
defun( vfpRGy0 (g) nth(4 g) )
defun( vfpRGpitch (g) nth(5 g) )
defun( vfpRGidx (g l c r) plus(times(plus(times(l vfpRGnc(g)) c) vfpRGnr(g)) r) )
defun( vfpRGget (g l c r) vfpRGocc(g)[vfpRGidx(g l c r)] )
defun( vfpRGset (g l c r v) vfpRGocc(g)[vfpRGidx(g l c r)] = v )
defun( vfpRGin (g c r) and(geqp(c 0) lessp(c vfpRGnc(g)) geqp(r 0) lessp(r vfpRGnr(g))) )
defun( vfpRGpassable (g l c r net) let( (o) o=vfpRGget(g l c r) or(null(o) equal(o net)) ) )
defun( vfpRGcol (g x) fix(quotient(difference(x vfpRGx0(g)) vfpRGpitch(g))) )
defun( vfpRGrow (g y) fix(quotient(difference(y vfpRGy0(g)) vfpRGpitch(g))) )
defun( vfpRGcx (g c) plus(vfpRGx0(g) times(plus(c 0.5) vfpRGpitch(g))) )
defun( vfpRGcy (g r) plus(vfpRGy0(g) times(plus(r 0.5) vfpRGpitch(g))) )

;; ---- Lee maze BFS: srcList/tgt = list(l c r); returns path or nil ----
defun( vfpRMaze (g srcList tgt net)
  let( (q visited prev found cur path k tl tc tr)
    visited = makeTable('vis nil)  prev = makeTable('prev nil)
    tl=nth(0 tgt) tc=nth(1 tgt) tr=nth(2 tgt)  q=nil
    foreach( s srcList
      k=vfpRGidx(g nth(0 s) nth(1 s) nth(2 s))
      unless(visited[k] visited[k]=t q=cons(s q)) )
    found=nil
    while( and(q null(found))
      cur=car(q) q=cdr(q)
      if( and(nth(0 cur)==tl nth(1 cur)==tc nth(2 cur)==tr)
        found=cur
        foreach( n list( list(nth(0 cur) plus(nth(1 cur) 1) nth(2 cur))
                         list(nth(0 cur) difference(nth(1 cur) 1) nth(2 cur))
                         list(nth(0 cur) nth(1 cur) plus(nth(2 cur) 1))
                         list(nth(0 cur) nth(1 cur) difference(nth(2 cur) 1))
                         list(difference(1 nth(0 cur)) nth(1 cur) nth(2 cur)) )
          let( (nl ncc nrr kk isTgt)
            nl=nth(0 n) ncc=nth(1 n) nrr=nth(2 n)
            isTgt=and(nl==tl ncc==tc nrr==tr)
            when( and( vfpRGin(g ncc nrr) (kk=vfpRGidx(g nl ncc nrr))
                       null(visited[kk]) or(isTgt vfpRGpassable(g nl ncc nrr net)) )
              visited[kk]=t prev[kk]=cur q=append(q list(n)) ) ) ) ) )
    if( found
      then path=list(found) cur=found
        while( prev[(k=vfpRGidx(g nth(0 cur) nth(1 cur) nth(2 cur)))]
          cur=prev[k] path=cons(cur path) )
        path
      else nil )
  )
)

;; cells currently claimed by a net (BFS sources for incremental routing)
defun( vfpRClaimedCells (g net)
  let( (out l c r)
    out=nil
    for( l 0 1 for( c 0 difference(vfpRGnc(g) 1) for( r 0 difference(vfpRGnr(g) 1)
      when(equal(vfpRGget(g l c r) net) out=cons(list(l c r) out)) ) ) )
    out
  )
)
defun( vfpRClaim (g path net)
  foreach( p path vfpRGset(g nth(0 p) nth(1 p) nth(2 p) net) )
)

;; ---- obstacles + terminals ------------------------------------------
;; mark M1 (layer 0) cells inside device instance bBoxes as obstacles (M2
;; stays free to route over devices); terminals are re-opened per net.
defun( vfpRMarkObstacles (g cv)
  foreach( i cv~>instances
    let( (bb c0 c1 r0 r1 c r)
      bb=i~>bBox
      c0=vfpRGcol(g xCoord(lowerLeft(bb)))  c1=vfpRGcol(g xCoord(upperRight(bb)))
      r0=vfpRGrow(g yCoord(lowerLeft(bb)))  r1=vfpRGrow(g yCoord(upperRight(bb)))
      c=c0 while(c<=c1 r=r0 while(r<=r1 when(vfpRGin(g c r) vfpRGset(g 0 c r 'obs)) r=r+1) c=c+1) ) )
)
;; physical point of a layout instTerm's pin (bBox centre of its first pin fig)
defun( vfpRTermPoint (it)
  let( (pin fig bb)
    pin=and(it~>term car(it~>term~>pins))  fig=and(pin pin~>fig)  bb=and(fig fig~>bBox)
    and(bb list( quotient(plus(xCoord(lowerLeft(bb)) xCoord(upperRight(bb))) 2.0)
                 quotient(plus(yCoord(lowerLeft(bb)) yCoord(upperRight(bb))) 2.0) )) )
)
;; per net -> list of grid cells list(0 col row) (terminal access on M1)
defun( vfpRNetTerms (g cv netName)
  let( (cells)
    foreach( i cv~>instances
      foreach( it i~>instTerms
        when( and(it~>net it~>net~>name==netName)
          let( (p c r) p=vfpRTermPoint(it)
            when(p c=vfpRGcol(g xCoord(p)) r=vfpRGrow(g yCoord(p))
              when(vfpRGin(g c r) cells=cons(list(0 c r) cells))) ) ) ) )
    cells
  )
)

;; ---- geometry: paint a routed path as M1/M2 wires + V1 vias ----------
defun( vfpRPaintCell (cv g l c r)
  let( (lp x y w) lp=if(l==0 list("M1" "drawing") list("M2" "drawing"))
    x=vfpRGcx(g c) y=vfpRGcy(g r) w=times(vfpRGpitch(g) 0.5)
    dbCreateRect(cv lp list(list(difference(x w) difference(y w)) list(plus(x w) plus(y w)))) )
)
defun( vfpRPaintVia (cv g c r)
  let( (x y v) x=vfpRGcx(g c) y=vfpRGcy(g r) v=0.13
    dbCreateRect(cv list("V1" "drawing") list(list(difference(x v) difference(y v)) list(plus(x v) plus(y v)))) )
)
defun( vfpRPaintPath (cv g path net)
  let( (prev)
    foreach( p path
      vfpRPaintCell(cv g nth(0 p) nth(1 p) nth(2 p))
      when( and(prev nth(0 prev) != nth(0 p)) vfpRPaintVia(cv g nth(1 p) nth(2 p)) )
      prev=p )
    vfpRClaim(g path net)
  )
)

;; ---- BASIC router backend -------------------------------------------
;; Route every net (>=2 terminals): seed with terminal 0, then maze each
;; remaining terminal to the net's claimed cells. Returns #nets routed.
defun( vfpRouterBasic (cv g)
  let( (snap nets routed)
    snap = vfpLayoutSnapshotConnectivity(cv)
    nets = append( vfpAlistGet(snap "named_nets") vfpAlistGet(snap "auto_nets") )
    routed = 0
    foreach( net nets
      let( (terms seed rest any)
        terms = vfpRNetTerms(g cv net)
        when( geqp(length(terms) 2)
          seed = car(terms)  rest = cdr(terms)  any = nil
          vfpRGset(g 0 nth(1 seed) nth(2 seed) net)
          foreach( tcell rest
            vfpRGset(g 0 nth(1 tcell) nth(2 tcell) net)
            let( (path) path=vfpRMaze(g vfpRClaimedCells(g net) tcell net)
              when(path vfpRPaintPath(cv g path net) any=t) ) )
          when(any routed=routed+1) ) ) )
    routed
  )
)

;; ---- pluggable backend registry + dispatch --------------------------
VFP_ROUTERS = makeTable('vfpRouters nil)
defun( vfpRegisterRouter (name fn) VFP_ROUTERS[name]=fn name )
defun( vfpActiveRouter () or( vfpStateGet('router) getShellEnvVar("VFP_ROUTER") "basic" ) )
vfpRegisterRouter("basic" 'vfpRouterBasic)

;; Route a layout cellview with the ACTIVE backend (default "basic"); an
;; external optimizer registers + selects its own. Returns the backend value.
defun( vfpLayoutRoute (cv @optional (pitch 0.6))
  prog( (bb g fn)
    bb=cv~>bBox
    g=vfpRGmake( fix(quotient(difference(xCoord(upperRight(bb)) xCoord(lowerLeft(bb))) pitch))
                 fix(quotient(difference(yCoord(upperRight(bb)) yCoord(lowerLeft(bb))) pitch))
                 xCoord(lowerLeft(bb)) yCoord(lowerLeft(bb)) pitch )
    vfpRMarkObstacles(g cv)
    fn = VFP_ROUTERS[vfpActiveRouter()]
    unless( fn vfpError(sprintf(nil "vfpLayoutRoute: no router backend %L" vfpActiveRouter())) return(nil) )
    return( apply(fn list(cv g)) )
  )
)

;; ---- expose as an L5 primitive (so it rides the registry + extension --
;; ---- channel; runs through the L4 transaction engine = reversible) ----
defun( vfpPrimRouteDescribe (cv params)
  let( (snap nets) snap = vfpLayoutSnapshotConnectivity(cv)
    nets = append( vfpAlistGet(snap "named_nets") vfpAlistGet(snap "auto_nets") )
    list( list("route" vfpActiveRouter() length(nets) "nets") )
  )
)
defun( vfpPrimRouteEdit (cv params)
  let( (n) n = vfpLayoutRoute(cv) and(n greaterp(n 0)) )
)
when( isCallable('vfpLayoutRegisterPrimitive)
  vfpLayoutRegisterPrimitive("route" 'vfpPrimRouteDescribe 'vfpPrimRouteEdit
                             "high" '("drc" "lvs")) )

