from collections import defaultdict

from ccspy.ast import Expr, Op, Step
from ccspy.dag import Key 
from ccspy.formula import Clause, Formula, normalize


def flatten(expr: Expr) -> Expr:
    if expr.is_literal:
        return expr

    lit_children = defaultdict(set)
    new_children = []
    
    def add_child(e):
        if e.is_literal and expr.op == Op.OR:
            # in this case, we can group matching literals by key to avoid unnecessary dnf expansion.
            # it's not totally clear whether it's better to do this here or in to_dnf() (or possibly even in
            # normalize()??, so this is a bit of an arbitrary choice...
            # TODO negative matches will need to be handled here, probably adding as separate clusters,
            # depending on specificity rules?
            # TODO wildcard matches also need to be handled specially here, either as a flag on the key or
            # a special entry in values...
            # TODO if this is done prior to normalize(), that function needs to be changed to understand
            # set-valued pos/neg literals... and might need to be changed for negative literals either way?
            lit_children[e.key.name].update(e.key.values)
        else:
            new_children.append(e)
    
    for e in map(flatten, expr.children):
        if not e.is_literal and e.op == expr.op:
            for c in e.children:
                add_child(c)
        else:
            add_child(e)
            
    for name in lit_children:
        new_children.append(Step(Key(name, lit_children[name])))
    return Expr(expr.op, new_children)


def to_dnf(expr: Expr, limit: int = 100) -> Formula:
    if expr.is_literal:
        return Formula([Clause([expr.key])])
    if expr.op == Op.OR:
        res = merge(map(lambda e: to_dnf(e, limit), expr.children))
        return res
    elif expr.op == Op.AND:
        return expand(limit, *map(lambda e: to_dnf(e, limit), expr.children))

                                        
def merge(forms) -> Formula:
    res = Formula(frozenset().union(*(f.elements() for f in forms)))
    res.shared = frozenset().union(*(f.shared for f in forms))
    return normalize(res)

                                        
def expand(limit: int, *forms):
    # first, build the subclause which is guaranteed to be common
    # to all clauses produced in this expansion. keep count of 
    # the non-trivial forms and the size of the result as we go...
    nontrivial = 0
    common = Clause([])
    result_size = 1
    for f in forms:
        result_size *= len(f)
        if len(f) == 1:
            common = common.union(f.first())
        else:
            nontrivial += 1
            
    if result_size > limit:
        raise ValueError("Expanded form would have {} clauses, which is more than the limit of {}. Consider increasing the limit or stratifying this rule.".format(result_size, limit))
            
    # next, perform the expansion...
    def exprec(forms) -> Formula:
        if len(forms) == 0:
            return Formula([Clause([])])
        first = forms[0]
        rest = exprec(forms[1:])
        cs = (c1.union(c2) for c1 in first.elements() for c2 in rest.elements())
        res = Formula(cs)
        res.shared = first.shared | rest.shared
        return res
    res = exprec(forms)

    # finally, gather shared subclauses and normalize...
    all_shared = set()
    if nontrivial > 0 and len(common) > 1:
        all_shared.add(common)
    if nontrivial > 1:
        for f in forms:
            if len(f) > 1:
                all_shared.update(c for c in f.elements() if len(c) > 1)
    res.shared = res.shared | all_shared
    return normalize(res)    