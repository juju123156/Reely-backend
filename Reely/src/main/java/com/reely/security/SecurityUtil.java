package com.reely.security;

import com.reely.exception.CustomException;
import com.reely.exception.ErrorCode;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;

public class SecurityUtil {
    public static Long getCurrentMemberPk() {
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth == null || !(auth.getPrincipal() instanceof CustomUserDetails)) {
            throw new CustomException(ErrorCode.USER_NOT_FOUND);
        }
        return ((CustomUserDetails) auth.getPrincipal()).getMemberPk();
    }
}
