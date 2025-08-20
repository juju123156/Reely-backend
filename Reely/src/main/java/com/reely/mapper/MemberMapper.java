package com.reely.mapper;

import com.reely.dto.EmailDto;
import com.reely.dto.MemberDto;
import org.apache.ibatis.annotations.Mapper;

import java.util.List;

@Mapper
public interface MemberMapper {
    List<MemberDto> findAll();

    Integer insertMember(MemberDto memberDto);

    Boolean existsByMemberId(MemberDto memberDto);

    MemberDto findMemberInfo(String memberId);

    Boolean existsByMemberEmail(MemberDto memberDto);

    MemberDto findMemberIdByMemberEmail(EmailDto emailDto);
}
