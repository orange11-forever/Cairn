HISTFILE=/dev/null

cairn_prompt() {
    cairn_status=$?
    cairn_branch=$(git symbolic-ref --quiet --short HEAD 2>/dev/null)
    PS1='\n\[\e[48;2;30;51;52m\e[1;36m\] \w \[\e[0m\]'
    if [[ -n $cairn_branch ]]; then
        PS1+=' \[\e[48;2;47;40;67m\e[1;35m\] git ${cairn_branch} \[\e[0m\]'
    fi
    if [[ $cairn_status -eq 0 ]]; then
        PS1+='\n\[\e[1;32m\]❯\[\e[0m\] '
    else
        PS1+=' \[\e[48;2;65;36;46m\e[1;31m\] exit ${cairn_status} \[\e[0m\]\n\[\e[1;31m\]❯\[\e[0m\] '
    fi
}

PROMPT_COMMAND=cairn_prompt
