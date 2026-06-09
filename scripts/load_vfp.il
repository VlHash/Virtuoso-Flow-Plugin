;; =====================================================================
;; load_vfp.il — one-shot loader for the Virtuoso CIW
;; ---------------------------------------------------------------------
;; In the Virtuoso CIW, load this file to load the plugin and initialize
;; it in a single step (no hard-coded paths needed):
;;
;;     load("<repo>/scripts/load_vfp.il")
;;
;; It resolves the repo root relative to itself, loads skill/vfp_init.il,
;; then calls vfpInit().
;; =====================================================================

let( (here root init)
  here = car(errset( get_filename(piport) ))
  if( and(here stringp(here) nequal(here ""))
    then
      root = simplifyFilename( strcat(here "/../..") )   ;; scripts/ -> repo root
      init = strcat(root "/skill/vfp_init.il")
      if( isFile(init)
        then load(init) vfpInit()
        else printf("[VFP] ERROR: cannot find %s\n" init)
      )
    else
      printf("[VFP] ERROR: could not resolve loader path; load skill/vfp_init.il directly.\n")
  )
)
