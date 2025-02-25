package com.reely.serviceImpl;

import com.reely.dto.MemberDto;
import com.reely.mapper.MemberMapper;
import com.reely.service.MemberService;
import jakarta.transaction.Transactional;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;

@Service
public class MemberServiceImpl implements MemberService {

    private final MemberMapper memberMapper;

    private final BCryptPasswordEncoder bCryptPasswordEncoder;

    @Autowired
    public MemberServiceImpl(MemberMapper memberMapper, BCryptPasswordEncoder bCryptPasswordEncoder) {
        this.memberMapper = memberMapper;
        this.bCryptPasswordEncoder = bCryptPasswordEncoder;
    }

    @Override
    public Boolean findMemberByMemberId(MemberDto memberDto) {
        return memberMapper.findMemberByMemberId(memberDto);
    }

    @Override
    @Transactional
    public Integer insertMember(MemberDto memberDto) {
        memberDto.setMemberPwd(bCryptPasswordEncoder.encode(memberDto.getMemberPwd())); // 암호화
        return memberMapper.insertMember(memberDto);
    }
}
