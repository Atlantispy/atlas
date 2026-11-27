# Isolated, persistent G25 point worker. SPDX-License-Identifier: AGPL-3.0-only
# No installation, network, file writes, phase removal or open-component buffer.
using MAGEMin_C, TOML, Base64, SHA, Libdl, LinearAlgebra

function reply(value)
    io = IOBuffer()
    TOML.print(io, value)
    println("ATLAS_G25\t", base64encode(take!(io)))
    flush(stdout)
end

Base.pkgversion(MAGEMin_C) == v"2.3.7" || error("requires pinned MAGEMin_C 2.3.7")
Threads.nthreads() == 1 || error("this worker requires exactly one Julia thread")
BLAS.set_num_threads(1)
ox = ["SiO2", "Al2O3", "CaO", "MgO", "FeO", "K2O", "Na2O", "TiO2", "O", "Cr2O3", "H2O"]
data = Initialize_MAGEMin("ig"; dataset=636, verbose=false, buffer="NONE", solver=1)
# Native phase_merge uses an unweighted midpoint of nonlinear internal variables,
# after calculating its convergence residual. Preserve the actual solved slots.
for gv in data.gv
    gv.merge_value = 0.0
    gv.br_max_tol = 1e-10
end
manifest = joinpath(dirname(Base.active_project()), "Manifest.toml")
native = filter(p -> occursin("magemin", lowercase(basename(p))), Libdl.dllist())
length(native) == 1 || error("expected one loaded MAGEMin library")
source_root = dirname(dirname(pathof(MAGEMin_C)))
source_files = sort([joinpath(folder,file) for (folder,_,files) in walkdir(source_root)
                     for file in files if endswith(file,".jl") || endswith(file,".toml")])
source_bytes = IOBuffer()
for file in source_files
    print(source_bytes, relpath(file,source_root), '\0', bytes2hex(sha256(read(file))), '\n')
end
reply(Dict("ready" => true, "wrapper_version" => string(Base.pkgversion(MAGEMin_C)),
           "julia_version" => string(VERSION), "manifest_sha256" => bytes2hex(sha256(read(manifest))),
           "wrapper_source_sha256" => bytes2hex(sha256(take!(source_bytes))),
           "native_sha256" => bytes2hex(sha256(read(only(native)))),
           "worker_sha256" => bytes2hex(sha256(read(@__FILE__)))))
try
    for line in eachline(stdin)
        line == "QUIT" && break
        try
            req = TOML.parse(String(base64decode(line)))
            p, t = Float64(req["p"]), Float64(req["t"])
            b = Float64.(req["b"])
            length(b) == 11 || error("exact ig component basis required")
            all(isfinite, b) && all(b .>= 0) && abs(sum(b)-1) < 1e-12 || error("invalid bulk")
            converted, converted_ox = convertBulk4MAGEMin(b, ox, "mol", "ig")
            converted ./= sum(converted)
            converted_ox == ox && maximum(abs.(converted .- b)) < 1e-12 ||
                error("wrapper would modify finite inventory; input refused")
            out = single_point_minimization(p/1e8, t-273.15, data;
                X=b, Xoxides=ox, sys_in="mol", scp=0, iguess=false, progressbar=false)
            out.status == 0 || error("equilibrium did not converge: $(out.status)")
            out.oxides == ox || error("changed component order")
            length(out.ph) == out.n_SS+out.n_PP || error("unexpected reservoir phase")
            phases = Any[]
            for name in unique(out.ph)
                indices = findall(==(name), out.ph)
                slots = [i <= out.n_SS ? out.SS_vec[i] : out.PP_vec[i-out.n_SS] for i in indices]
                # Sum conserved component amounts only: do NOT invent one phase
                # by averaging xeos and then evaluating nonlinear composition.
                # LP support vertices of the same smooth phase can change count.
                # Keep their coordinate envelope as a branch diagnostic; refuse
                # widely separated same-model states (unhandled solvus branch).
                coords = [vcat(q.Comp, i <= out.n_SS ? q.compVariables : Float64[])
                          for (i, q) in zip(indices, slots)]
                length(unique(length.(coords))) == 1 || error("incompatible phase branches")
                lows = [minimum(x[j] for x in coords) for j in eachindex(first(coords))]
                highs = [maximum(x[j] for x in coords) for j in eachindex(first(coords))]
                maximum(highs .- lows) <= 1e-3 || error("unresolved same-phase support spread")
                amounts = [sum(out.ph_frac[i]*q.Comp[j] for (i,q) in zip(indices,slots)) for j in 1:11]
                push!(phases, Dict("key" => name, "amounts" => amounts,
                                   "coordinates" => vcat(lows, highs)))
            end
            reply(Dict("ok" => true, "p" => out.P_kbar*1e8, "t" => out.T_C+273.15,
                "bulk" => collect(out.bulk), "mu" => 1000 .* out.Gamma,
                "g" => 1000*out.G_system, "phases" => phases,
                "database" => out.database, "dataset" => out.dataset,
                "native_version" => out.MAGEMin_ver, "bulk_residual" => out.bulk_res_norm,
                "solve_ms" => out.time_ms))
        catch err
            reply(Dict("ok" => false, "error" => sprint(showerror, err)))
        end
    end
finally
    Finalize_MAGEMin(data)
end
