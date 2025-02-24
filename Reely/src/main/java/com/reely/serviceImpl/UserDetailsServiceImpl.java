package com.reely.serviceImpl;

import com.reely.dto.MemberDto;
import com.reely.mapper.MemberMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.security.core.userdetails.User;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.core.userdetails.UsernameNotFoundException;
import org.springframework.stereotype.Service;
import org.springframework.util.ObjectUtils;

import java.util.Collections;

@Service
@Slf4j
public class UserDetailsServiceImpl implements UserDetailsService {

    private final MemberMapper memberMapper;

    @Autowired
    public UserDetailsServiceImpl(MemberMapper memberRepository) {
        this.memberMapper = memberRepository;
    }


    @Override
    public UserDetails loadUserByUsername(String memberId) throws UsernameNotFoundException {
        MemberDto member = memberMapper.findMemberInfo(memberId);

        if (ObjectUtils.isEmpty(member)) {
            log.error("사용자 정보를 찾을 수 없음: {}", memberId);
            throw new UsernameNotFoundException("사용자를 찾을 수 없습니다: " + memberId);
        }

        return User.builder()
                .username(member.getMemberId())
                .password(member.getMemberPwd()) // DB에서 가져온 암호화된 비밀번호
                .authorities(Collections.emptyList()) // 권한 설정 (필요하면 추가 가능)
                .build();
    }
}
